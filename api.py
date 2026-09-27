"""Spotify Partner API client.

Replaces spotipy with direct Partner API calls.
Uses GraphQL-style queries via api-partner.spotify.com/pathfinder/v2/query.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

import requests

from librelyrics.exceptions import (
    LyricsNotFound,
    NotValidSp_Dc,
    ProviderError,
    RateLimitError,
    TOTPGenerationException,
    TransientProviderError,
)
from spotify.totp import TOTP

logger = logging.getLogger("librelyrics.modules.spotify.api")

# URLs
TOKEN_URL = "https://open.spotify.com/api/token"
CLIENT_TOKEN_URL = "https://clienttoken.spotify.com/v1/clienttoken"
PARTNER_API_URL = "https://api-partner.spotify.com/pathfinder/v2/query"
LYRICS_URL = "https://spclient.wg.spotify.com/color-lyrics/v2/track/{}"
SPOTIFY_HOME = "https://open.spotify.com"

# Pagination
PAGE_SIZE = 100

# User agent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Regex patterns for Spotify URLs and URIs
TRACK_ID_PATTERN = re.compile(
    r"(?:spotify\.com/(?:[a-zA-Z0-9-]+/)?track/|spotify:track:)([a-zA-Z0-9]+)"
)
ALBUM_ID_PATTERN = re.compile(
    r"(?:spotify\.com/(?:[a-zA-Z0-9-]+/)?album/|spotify:album:)([a-zA-Z0-9]+)"
)
PLAYLIST_ID_PATTERN = re.compile(
    r"(?:spotify\.com/(?:[a-zA-Z0-9-]+/)?playlist/|spotify:playlist:)([a-zA-Z0-9]+)"
)


def extract_track_id(url: str) -> str | None:
    """Extract track ID from Spotify URL or URI."""
    if match := TRACK_ID_PATTERN.search(url):
        return match.group(1)
    return None


def extract_album_id(url: str) -> str | None:
    """Extract album ID from Spotify URL or URI."""
    if match := ALBUM_ID_PATTERN.search(url):
        return match.group(1)
    return None


def extract_playlist_id(url: str) -> str | None:
    """Extract playlist ID from Spotify URL or URI."""
    if match := PLAYLIST_ID_PATTERN.search(url):
        return match.group(1)
    return None


# GraphQL persisted query hashes
# These hashes may need to be updated when Spotify updates their web player
# To find new hashes, inspect network requests in browser DevTools on open.spotify.com
OPERATION_HASHES = {
    # Hash for getTrack operation
    "getTrack": "612585ae06ba435ad26369870deaae23b5c8800a256cd8a57e08eddc25a37294",
    # Hash for getAlbum operation
    "getAlbum": "b9bfabef66ed756e5e13f68a942deb60bd4125ec1f1be8cc42769dc0259b4b10",
    # Hash for getPlaylist operation
    "getPlaylist": "7982b11e21535cd2594badc40030b745671b61a1fa66766e569d45e6364f3422",
    # Hash for search operation
    "searchSuggestions": "b50ebd72524415b132ddaca04158fd7aca529da28be322c9924643c0633df5bd",
}


class SpotifyClient:
    """Client for Spotify's Partner API.

    Uses the Partner API (api-partner.spotify.com) for metadata
    and spclient for lyrics. No sp_dc cookie needed for public data.
    """

    def __init__(
        self,
        sp_dc: str | None = None,
        totp_secret_cipher_dict_url: str | None = None,
    ) -> None:
        """Initialize the Spotify client.

        Args:
            sp_dc: Optional Spotify sp_dc cookie for authenticated requests.
        """
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            }
        )

        if sp_dc:
            self.session.cookies.set("sp_dc", sp_dc)

        self.access_token: str | None = None
        self.client_token: str | None = None
        self.client_id: str | None = None
        self.device_id: str | None = None
        self.client_version: str | None = None
        self.totp = TOTP(secret_cipher_dict_url=totp_secret_cipher_dict_url)

        self._initialize()

    def _initialize(self) -> None:
        """Initialize tokens and session info."""
        self._get_session_info()
        self._get_access_token()
        self._get_client_token()
        logger.debug("Spotify client initialized")

    def _get_session_info(self) -> None:
        """Get client version from Spotify home page."""
        try:
            resp = self.session.get(SPOTIFY_HOME, timeout=10)

            # Extract client version from appServerConfig
            match = re.search(
                r'<script id="appServerConfig" type="text/plain">([^<]+)</script>',
                resp.text,
            )
            if match:
                try:
                    decoded = base64.b64decode(match.group(1)).decode("utf-8")
                    config = json.loads(decoded)
                    self.client_version = config.get("clientVersion", "")
                except Exception:
                    pass

            # Get device ID from cookies
            for cookie in resp.cookies:
                if cookie.name == "sp_t":
                    self.device_id = cookie.value

            if not self.client_version:
                self.client_version = "1.2.46.25.g7f189073"

        except Exception as e:
            logger.warning(f"Failed to get session info: {e}")
            self.client_version = "1.2.46.25.g7f189073"

    def _get_access_token(self) -> None:
        """Get access token using TOTP."""
        try:
            totp_code = self.totp.generate(
                timestamp=int(1e3 * __import__("time").time())
            )

            params = {
                "reason": "init",
                "productType": "web-player",
                "totp": totp_code,
                "totpVer": str(self.totp.version),
                "totpServer": totp_code,
            }

            resp = self.session.get(TOKEN_URL, params=params, timeout=10)

            if resp.status_code != 200:
                raise NotValidSp_Dc(
                    f"Failed to get access token: HTTP {resp.status_code}"
                )

            data = resp.json()
            self.access_token = data.get("accessToken")
            self.client_id = data.get("clientId")

            # Get device ID from cookies if not already set
            for cookie in resp.cookies:
                if cookie.name == "sp_t":
                    self.device_id = cookie.value

            # Generate a device ID if not found in cookies
            if not self.device_id:
                import uuid

                self.device_id = str(uuid.uuid4())
                logger.debug("Generated fallback device_id")

            if not self.access_token:
                raise NotValidSp_Dc("No access token in response")

            logger.debug("Got access token")

        except requests.RequestException as e:
            raise TOTPGenerationException(f"Failed to get access token: {e}") from e

    def _get_client_token(self) -> None:
        """Get client token for Partner API."""
        if not self.client_id or not self.client_version:
            raise ProviderError("Missing client info for client token")

        payload = {
            "client_data": {
                "client_version": self.client_version,
                "client_id": self.client_id,
                "js_sdk_data": {
                    "device_brand": "unknown",
                    "device_model": "unknown",
                    "os": "windows",
                    "os_version": "NT 10.0",
                    "device_id": self.device_id,
                    "device_type": "computer",
                },
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            resp = self.session.post(
                CLIENT_TOKEN_URL,
                json=payload,
                headers=headers,
                timeout=10,
            )

            if resp.status_code != 200:
                raise ProviderError(
                    f"Failed to get client token: HTTP {resp.status_code}"
                )

            data = resp.json()

            if data.get("response_type") != "RESPONSE_GRANTED_TOKEN_RESPONSE":
                raise ProviderError("Invalid client token response")

            granted_token = data.get("granted_token", {})
            self.client_token = granted_token.get("token")

            if not self.client_token:
                raise ProviderError("No client token in response")

            logger.debug("Got client token")

        except requests.RequestException as e:
            raise ProviderError(f"Failed to get client token: {e}") from e

    def _query(self, payload: dict) -> dict:
        """Execute a Partner API query.

        Args:
            payload: GraphQL-style query payload.

        Returns:
            Response data.
        """
        if not self.access_token or not self.client_token:
            self._initialize()

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Client-Token": self.client_token,
            "Spotify-App-Version": self.client_version or "",
            "Content-Type": "application/json;charset=UTF-8",
            "Accept": "application/json",
            "Origin": "https://open.spotify.com",
            "Referer": "https://open.spotify.com/",
            "Accept-Language": "en",
            "App-Platform": "WebPlayer",
        }

        try:
            logger.debug(f"Sending Partner API request: {payload}")
            resp = self.session.post(
                PARTNER_API_URL,
                json=payload,
                headers=headers,
                timeout=15,
            )
            logger.debug(f"Partner API response: {resp.status_code} - {resp.text[:500]}")

            if resp.status_code == 412:
                # Precondition failed - likely need to refresh tokens
                logger.warning("Got 412, refreshing tokens...")
                self._initialize()
                headers["Authorization"] = f"Bearer {self.access_token}"
                headers["Client-Token"] = self.client_token
                resp = self.session.post(
                    PARTNER_API_URL,
                    json=payload,
                    headers=headers,
                    timeout=15,
                )

            if resp.status_code != 200:
                logger.error(
                    f"Partner API error: {resp.status_code} - {resp.text[:500]}"
                )
                raise ProviderError(f"Partner API error: HTTP {resp.status_code}")

            return resp.json()

        except requests.RequestException as e:
            raise ProviderError(f"Partner API request failed: {e}") from e

    def query(
        self, operation_name: str, variables: dict[str, Any], hash_key: str
    ) -> dict[str, Any]:
        """Build and execute a GraphQL query.

        Args:
            operation_name: GraphQL operation name.
            variables: Query variables.
            hash_key: Key into OPERATION_HASHES for the persisted query hash.

        Returns:
            Response data.
        """
        payload = {
            "operationName": operation_name,
            "variables": variables,
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": OPERATION_HASHES[hash_key],
                },
            },
        }
        return self._query(payload)

    def get_track(self, track_id: str) -> dict[str, Any]:
        """Get track metadata.

        Args:
            track_id: Spotify track ID.

        Returns:
            Track metadata dictionary.
        """
        result = self.query(
            "getTrack", {"uri": f"spotify:track:{track_id}"}, "getTrack"
        )

        data = result.get("data", {}).get("trackUnion", {})
        if not data:
            raise LyricsNotFound(f"Track not found: {track_id}")

        # Extract artists
        artists = []
        artists_data = data.get("artists", {}).get("items", [])
        for artist in artists_data:
            profile = artist.get("profile", {})
            if profile.get("name"):
                artists.append({"name": profile["name"]})

        # If no artists from main field, try firstArtist/otherArtists
        if not artists:
            for field in ["firstArtist", "otherArtists"]:
                items = data.get(field, {}).get("items", [])
                for item in items:
                    profile = item.get("profile", {})
                    if profile.get("name"):
                        artists.append({"name": profile["name"]})

        # Extract album info
        album_data = data.get("albumOfTrack", {})
        album = {
            "name": album_data.get("name", ""),
            "id": album_data.get("id", ""),
        }

        # Extract duration
        duration_data = data.get("duration", {})
        duration_ms = int(duration_data.get("totalMilliseconds", 0))

        return {
            "id": data.get("id", track_id),
            "name": data.get("name", ""),
            "artists": artists,
            "album": album,
            "duration_ms": duration_ms,
            "track_number": int(data.get("trackNumber", 0)),
            "disc_number": int(data.get("discNumber", 1)),
            "explicit": data.get("contentRating", {}).get("label") == "EXPLICIT",
        }

    def get_lyrics(self, track_id: str) -> dict[str, Any] | None:
        """Fetch lyrics for a track.

        Retry and back-off are the core's job: this only classifies the response.
        Rate limits, server errors and rejected tokens are raised so
        ``LyricsModule.retry_call`` retries them; only 404 means "no lyrics".

        Args:
            track_id: Spotify track ID.

        Returns:
            Lyrics JSON data, or None if the track has no lyrics.

        Raises:
            RateLimitError: The endpoint asked us to slow down.
            TransientProviderError: Server error, dropped connection, or a
                rejected access token (the token is dropped so the retry
                acquires a fresh one).
            ProviderError: Any other rejected request.
        """
        if not self.access_token:
            self._get_access_token()

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "App-Platform": "WebPlayer",
        }

        url = LYRICS_URL.format(track_id)
        params = {"format": "json", "market": "from_token"}

        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=10)
        except requests.RequestException as e:
            raise TransientProviderError(f"Spotify lyrics request failed: {e}") from e

        if resp.status_code == 200:
            try:
                payload = resp.json()
            except ValueError as e:
                raise TransientProviderError(
                    f"Spotify lyrics response was not JSON: {e}"
                ) from e
            logger.debug(f"Fetched lyrics for: {track_id}")
            return payload

        if resp.status_code == 404:
            logger.debug(f"No lyrics available for: {track_id}")
            return None

        if resp.status_code == 429:
            try:
                retry_after = float(resp.headers.get("Retry-After", ""))
            except (TypeError, ValueError):
                retry_after = None
            raise RateLimitError(
                f"Spotify lyrics throttled: HTTP 429 for {track_id}",
                retry_after=retry_after,
            )

        if resp.status_code >= 500:
            raise TransientProviderError(
                f"Spotify lyrics request failed: HTTP {resp.status_code} for {track_id}"
            )

        if resp.status_code == 401:
            # Drop the token so the retry fetches a fresh one instead of
            # replaying the rejected request with the same credentials.
            self.access_token = None
            raise TransientProviderError(
                f"Spotify lyrics request rejected the access token for {track_id}"
            )

        # Reporting these as "no lyrics" would hide a rejected request behind an
        # empty download.
        raise ProviderError(
            f"Spotify lyrics request failed: HTTP {resp.status_code} for {track_id}"
        )

    def get_album(self, album_id: str) -> dict[str, Any]:
        """Get album metadata, following every page of tracks.

        Args:
            album_id: Spotify album ID.

        Returns:
            Album metadata dictionary.
        """
        data: dict[str, Any] = {}
        artists: list[dict[str, str]] = []
        tracks: list[dict[str, Any]] = []
        offset = 0

        while True:
            result = self.query(
                "getAlbum",
                {
                    "uri": f"spotify:album:{album_id}",
                    "locale": "",
                    "offset": offset,
                    "limit": PAGE_SIZE,
                },
                "getAlbum",
            )
            page = result.get("data", {}).get("albumUnion", {})
            if not page:
                if not data:
                    raise LyricsNotFound(f"Album not found: {album_id}")
                break

            if not data:
                data = page
                for item in page.get("artists", {}).get("items", []):
                    profile = item.get("profile", {})
                    if profile.get("name"):
                        artists.append({"name": profile["name"]})

            items = page.get("tracksV2", {}).get("items", [])
            for item in items:
                track = item.get("track", {})
                if not track:
                    continue

                track_uri = track.get("uri", "")
                track_id = track_uri.split(":")[-1] if ":" in track_uri else ""

                track_artists = []
                for a in track.get("artists", {}).get("items", []):
                    if a.get("profile", {}).get("name"):
                        track_artists.append({"name": a["profile"]["name"]})

                tracks.append(
                    {
                        "id": track_id,
                        "name": track.get("name", ""),
                        "artists": track_artists,
                        "duration_ms": int(
                            track.get("duration", {}).get("totalMilliseconds", 0)
                        ),
                        "track_number": int(track.get("trackNumber", 0)),
                        "disc_number": int(track.get("discNumber", 1)),
                    }
                )

            offset += len(items)
            total = int(page.get("tracksV2", {}).get("totalCount", 0) or 0)
            logger.debug("Album %s: %d/%d tracks", album_id, offset, total)
            if not items or offset >= total:
                break

        # Extract date
        date_info = data.get("date", {})
        release_date = date_info.get("isoString", "")
        if release_date and "T" in release_date:
            release_date = release_date.split("T")[0]

        return {
            "id": album_id,
            "name": data.get("name", ""),
            "artists": artists,
            "tracks": tracks,
            "total_tracks": len(tracks),
            "release_date": release_date,
            "label": data.get("label", ""),
        }

    def get_album_tracks(self, album_id: str) -> list[str]:
        """Get all track IDs from an album.

        Args:
            album_id: Spotify album ID.

        Returns:
            List of track IDs.
        """
        album = self.get_album(album_id)
        return [t["id"] for t in album.get("tracks", []) if t.get("id")]

    def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        """Get playlist metadata.

        Args:
            playlist_id: Spotify playlist ID.

        Returns:
            Playlist metadata dictionary.
        """
        data: dict[str, Any] = {}
        tracks: list[dict[str, Any]] = []
        fetched = 0
        total = 0

        while True:
            result = self.query(
                "fetchPlaylist",
                {
                    "enableWatchFeedEntrypoint": True,
                    "uri": f"spotify:playlist:{playlist_id}",
                    "offset": fetched,
                    "limit": PAGE_SIZE,
                },
                "getPlaylist",
            )
            page = result.get("data", {}).get("playlistV2", {})
            if not page:
                if not data:
                    raise LyricsNotFound(f"Playlist not found: {playlist_id}")
                break

            if not data:
                data = page

            content = page.get("content", {})
            items = content.get("items", [])
            for item in items:
                track_data = item.get("itemV2", {}).get("data", {})
                if not track_data:
                    continue

                track_uri = track_data.get("uri", "")
                track_id = track_uri.split(":")[-1] if ":" in track_uri else ""

                if not track_id:
                    track_id = track_data.get("id", "")

                if not track_id:
                    continue

                track_artists = []
                for a in track_data.get("artists", {}).get("items", []):
                    if a.get("profile", {}).get("name"):
                        track_artists.append({"name": a["profile"]["name"]})

                album_data = track_data.get("albumOfTrack", {})

                tracks.append(
                    {
                        "id": track_id,
                        "name": track_data.get("name", ""),
                        "artists": track_artists,
                        "album": {
                            "name": album_data.get("name", ""),
                            "id": album_data.get("uri", "").split(":")[-1]
                            if album_data.get("uri")
                            else "",
                        },
                    }
                )

            fetched += len(items)
            total = int(content.get("totalCount", 0) or 0)
            logger.debug("Playlist %s: %d/%d items", playlist_id, fetched, total)
            if not items or fetched >= total:
                break

        owner_data = data.get("ownerV2", {}).get("data", {})
        owner = {
            "display_name": owner_data.get("name", ""),
        }

        return {
            "id": playlist_id,
            "name": data.get("name", ""),
            "description": data.get("description", ""),
            "owner": owner,
            "tracks": {
                "total": total or len(tracks),
                "items": tracks,
            },
        }

    def get_playlist_tracks(self, playlist_id: str) -> list[str]:
        """Get all track IDs from a playlist.

        Args:
            playlist_id: Spotify playlist ID.

        Returns:
            List of track IDs.
        """
        playlist = self.get_playlist(playlist_id)
        return [
            t["id"] for t in playlist.get("tracks", {}).get("items", []) if t.get("id")
        ]

    def search(
        self,
        query: str,
        search_type: str = "track",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search Spotify tracks using the searchSuggestions GraphQL endpoint.

        The endpoint returns ranked hits of mixed types under
        data.searchV2.topResultsV2.itemsV2[].item.data; only Track hits are
        returned. ``search_type`` is accepted for call compatibility; the
        persisted query only supports track search.
        """
        if not self.access_token:
            self._initialize()
        logger.debug("Searching for %r (limit=%d)", query, limit)

        result = self.query(
            "searchSuggestions",
            {
                "query": query,
                "limit": limit,
                "offset": 0,
                "includeAuthors": False,
                "includeAlbumPreReleases": False,
            },
            "searchSuggestions",
        )

        hits = (
            result.get("data", {})
            .get("searchV2", {})
            .get("topResultsV2", {})
            .get("itemsV2", [])
        )

        tracks: list[dict[str, Any]] = []
        for hit in hits:
            track = hit.get("item", {}).get("data", {})
            if track.get("__typename") != "Track" or not track.get("id"):
                continue
            album = track.get("albumOfTrack") or {}
            artists = [
                {
                    "id": (artist.get("uri") or "").split(":")[-1],
                    "name": artist.get("profile", {}).get("name", ""),
                }
                for artist in (track.get("artists") or {}).get("items", [])
                if artist.get("profile", {}).get("name")
            ]
            tracks.append(
                {
                    "id": track["id"],
                    "name": track.get("name", ""),
                    "artists": artists,
                    "album": {
                        "id": album.get("id", ""),
                        "name": album.get("name", ""),
                    },
                    "duration_ms": int(
                        (track.get("duration") or {}).get("totalMilliseconds", 0)
                    ),
                }
            )
            if len(tracks) >= limit:
                break

        return {"tracks": {"items": tracks, "total": len(tracks)}}
