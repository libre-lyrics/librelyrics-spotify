"""Spotify lyrics module implementation.

This is the main LyricsModule implementation for Spotify.
Handles track, album, and playlist URLs.
"""
from __future__ import annotations

import logging
import re
from typing import ClassVar

from librelyrics.exceptions import ConfigurationError, LyricsNotFound
from librelyrics.models import LyricsLine, LyricsResponse, TrackQuery
from librelyrics.modules.base import (LyricsModule, LyricsType,
                                      ModuleCapability, ModuleMeta)
from spotify.api import (SpotifyClient, extract_album_id, extract_playlist_id,
                         extract_track_id)
from spotify import totp as spotify_totp

logger = logging.getLogger('librelyrics.modules.spotify')


class SpotifyModule(LyricsModule):
    """Spotify lyrics provider module.
    
    Fetches lyrics from Spotify's internal color-lyrics API.
    Supports track, album, and playlist URLs.
    """
    
    META: ClassVar[ModuleMeta] = ModuleMeta(
        id="spotify",
        name="Spotify",
        regex=re.compile(r"(?:open\.)?spotify\.com/(?:[a-zA-Z0-9-]+/)?(track|album|playlist)/"),
        requires_auth=True,
        description="Fetch lyrics from Spotify",
        lyrics_types=frozenset({LyricsType.PLAIN, LyricsType.SYNCED}),
        capabilities=frozenset({
            ModuleCapability.SINGLE_TRACK,
            ModuleCapability.ALBUM,
            ModuleCapability.PLAYLIST,
            ModuleCapability.RESOLVE,
            ModuleCapability.SEARCH,
        }),
        config_schema={
            'sp_dc': 'Spotify sp_dc cookie (see README)',
            'synced_lyrics': 'Prefer synced lyrics (true/false)',
            'totp_secret_cipher_dict_url': (
                'Optional override for the Spotify TOTP secret dictionary URL'
            ),
        },
    )
    LIBRELYRICS_API_VERSION: ClassVar[int] = 2
    
    @classmethod
    def matches(cls, query: TrackQuery) -> bool:
        if query.url:
            return super().matches(query)
        return bool(query.artist and query.title)

    @classmethod
    def classify_url(cls, url: str | None) -> str | None:
        if not url:
            return None
        if extract_playlist_id(url):
            return "playlist"
        if extract_album_id(url):
            return "album"
        if extract_track_id(url):
            return "track"
        return None

    def __init__(self, query: TrackQuery, config: dict) -> None:
        super().__init__(query, config)
        self._client: SpotifyClient | None = None
    
    def _ensure_client(self) -> None:
        """Ensure Spotify client is initialized with current config."""
        if self._client is None:
            sp_dc = self.config.get('sp_dc')
            totp_secret_cipher_dict_url = self.config.get(
                'totp_secret_cipher_dict_url'
            )
            if totp_secret_cipher_dict_url:
                spotify_totp.SECRET_CIPHER_DICT_URL = totp_secret_cipher_dict_url

            self._client = SpotifyClient(
                sp_dc=sp_dc or None,
                totp_secret_cipher_dict_url=totp_secret_cipher_dict_url or None,
            )
            logger.debug("Initialized Spotify client")
    
    @property
    def client(self) -> SpotifyClient:
        """Get the Spotify client instance."""
        if self._client is None:
            self._ensure_client()
        return self._client  # type: ignore
    
    @staticmethod
    def default_config() -> dict:
        """Return default Spotify configuration."""
        return {
            'sp_dc': '',
            'synced_lyrics': True,
            'totp_secret_cipher_dict_url': '',
        }
    
    @staticmethod
    def validate_config(config: dict) -> None:
        """Validate Spotify configuration.
        
        Raises:
            ConfigurationError: If sp_dc is missing or empty.
        """
        if not config.get('sp_dc'):
            raise ConfigurationError(
                "Spotify plugin requires 'sp_dc' cookie. "
                "See README for instructions on finding it."
            )
    
    def resolve(self) -> TrackQuery:
        """Resolve Spotify track metadata from URL."""
        if not self.url:
            return self.query
        track_id = extract_track_id(self.url)
        if not track_id:
            return self.query
        try:
            track_data = self.client.get_track(track_id)
            artists = ', '.join(a['name'] for a in track_data.get('artists', [])) or None
            return TrackQuery(
                url=self.url,
                artist=self.query.artist or artists,
                title=self.query.title or track_data.get('name'),
                album=self.query.album or track_data.get('album', {}).get('name'),
                duration_ms=self.query.duration_ms or track_data.get('duration_ms'),
            )
        except Exception as e:
            logger.warning(f"Failed to resolve Spotify track: {e}")
            return self.query

    def list_tracks(self) -> list[TrackQuery]:
        """List metadata for every track in the album or playlist."""
        if not self.url:
            return []

        album_id = extract_album_id(self.url)
        if album_id:
            album_data = self.client.get_album(album_id)
            album_name = album_data.get('name')
            tracks: list[TrackQuery] = []
            for t in album_data.get('tracks', []):
                t_id = t.get('id')
                if not t_id:
                    continue
                artists = ', '.join(a['name'] for a in t.get('artists', [])) or None
                tracks.append(
                    TrackQuery(
                        url=f"https://open.spotify.com/track/{t_id}",
                        artist=artists,
                        title=t.get('name'),
                        album=album_name,
                        duration_ms=t.get('duration_ms'),
                    )
                )
            return tracks

        playlist_id = extract_playlist_id(self.url)
        if playlist_id:
            playlist_data = self.client.get_playlist(playlist_id)
            tracks_info = playlist_data.get('tracks', {}).get('items', [])
            tracks = []
            for t in tracks_info:
                t_id = t.get('id')
                if not t_id:
                    continue
                artists = ', '.join(a['name'] for a in t.get('artists', [])) or None
                album_name = t.get('album', {}).get('name')
                tracks.append(
                    TrackQuery(
                        url=f"https://open.spotify.com/track/{t_id}",
                        artist=artists,
                        title=t.get('name'),
                        album=album_name,
                        duration_ms=t.get('duration_ms'),
                    )
                )
            return tracks

        # Single track fallback
        track_id = extract_track_id(self.url)
        if track_id:
            return [self.resolve()]

        raise LyricsNotFound(f"Could not extract track, album, or playlist from URL: {self.url}")

    def _search_track_id(self) -> str:
        artist = (self.query.artist or "").strip()
        title = (self.query.title or "").strip()
        if not artist or not title:
            raise LyricsNotFound("Artist and title are required to search Spotify")
        query = f'track:"{title}" artist:"{artist}"'
        data = self.client.search(query, search_type="track", limit=5)
        items = (data.get("tracks") or {}).get("items") or []
        if not items:
            raise LyricsNotFound(f"No Spotify match for: {artist} - {title}")
        track_id = items[0].get("id")
        if not track_id:
            raise LyricsNotFound(f"No Spotify match for: {artist} - {title}")
        return track_id

    def fetch(self) -> LyricsResponse:
        """Fetch lyrics for the configured URL or metadata search.
        
        Returns:
            LyricsResponse with lyrics data.
            
        Raises:
            LyricsNotFound: If lyrics are not available.
        """
        if not self.url:
            return self._fetch_track_lyrics(self._search_track_id())

        track_id = extract_track_id(self.url)
        
        if not track_id:
            # Check if it's an album or playlist (batch fetch not supported here)
            if extract_album_id(self.url) or extract_playlist_id(self.url):
                raise LyricsNotFound(
                    "Album/playlist batch fetch should use fetch_batch(). "
                    "Single fetch() requires a track URL."
                )
            raise LyricsNotFound(f"Could not extract track ID from URL: {self.url}")
        
        return self._fetch_track_lyrics(track_id)
    
    def _fetch_track_lyrics(self, track_id: str) -> LyricsResponse:
        """Fetch lyrics for a single track.
        
        Args:
            track_id: Spotify track ID.
            
        Returns:
            LyricsResponse with lyrics data.
            
        Raises:
            LyricsNotFound: If lyrics are not available.
        """
        if not self.config.get('sp_dc'):
            raise ConfigurationError(
                "Spotify plugin requires 'sp_dc' in configuration to fetch lyrics. "
                "Run 'librelyrics --config' to set it up."
            )
        # Get track metadata
        track_data = self.client.get_track(track_id)
        
        # Get lyrics
        lyrics_json = self.client.get_lyrics(track_id)
        if not lyrics_json or 'lyrics' not in lyrics_json:
            raise LyricsNotFound(f"No lyrics available for: {track_data['name']}")
        
        # Parse lyrics
        lyrics_data = lyrics_json['lyrics']
        sync_type = lyrics_data.get('syncType', 'UNSYNCED')
        is_synced = sync_type == 'LINE_SYNCED' and self.config.get('synced_lyrics', True)
        
        lines: list[LyricsLine] = []
        for line in lyrics_data.get('lines', []):
            if is_synced:
                start_ms = int(line.get('startTimeMs', 0))
                lines.append(LyricsLine(text=line['words'], start_ms=start_ms))
            else:
                lines.append(LyricsLine(text=line['words']))
        
        # Extract artist names
        artists = ', '.join(artist['name'] for artist in track_data['artists'])
        
        logger.debug(f"Fetched lyrics for: {track_data['name']} - {artists}")
        
        return LyricsResponse(
            title=track_data['name'],
            artist=artists,
            album=track_data['album']['name'],
            lyrics=lines,
            source=self.META.name,
            synced=is_synced,
            duration_ms=track_data.get('duration_ms'),
            metadata={
                'track_id': track_id,
                'album_id': track_data['album']['id'],
                'explicit': track_data.get('explicit', False),
                'track_number': track_data.get('track_number'),
            }
        )
    
    def fetch_album(self) -> list[LyricsResponse]:
        """Fetch lyrics for all tracks in an album.
        
        Returns:
            List of LyricsResponse objects.
        """
        album_id = extract_album_id(self.url)
        if not album_id:
            raise LyricsNotFound(f"Could not extract album ID from URL: {self.url}")
        
        track_ids = self.client.get_album_tracks(album_id)
        return self._fetch_multiple_tracks(track_ids)
    
    def fetch_playlist(self) -> list[LyricsResponse]:
        """Fetch lyrics for all tracks in a playlist.
        
        Returns:
            List of LyricsResponse objects.
        """
        playlist_id = extract_playlist_id(self.url)
        if not playlist_id:
            raise LyricsNotFound(f"Could not extract playlist ID from URL: {self.url}")
        
        track_ids = self.client.get_playlist_tracks(playlist_id)
        return self._fetch_multiple_tracks(track_ids)
    
    def _fetch_multiple_tracks(self, track_ids: list[str]) -> list[LyricsResponse]:
        """Fetch lyrics for multiple tracks.
        
        Args:
            track_ids: List of track IDs.
            
        Returns:
            List of LyricsResponse objects for tracks with available lyrics.
        """
        results: list[LyricsResponse] = []
        
        for track_id in track_ids:
            try:
                response = self._fetch_track_lyrics(track_id)
                results.append(response)
            except LyricsNotFound:
                logger.warning(f"No lyrics found for track: {track_id}")
                continue
            except Exception as e:
                logger.warning(f"Failed to fetch lyrics for track {track_id}: {e}")
                continue
        
        return results
    
    def get_album_info(self) -> dict:
        """Get album metadata for the URL.
        
        Returns:
            Album metadata dictionary.
        """
        album_id = extract_album_id(self.url)
        if not album_id:
            raise LyricsNotFound(f"Could not extract album ID from URL: {self.url}")
        return self.client.get_album(album_id)
    
    def get_playlist_info(self) -> dict:
        """Get playlist metadata for the URL.
        
        Returns:
            Playlist metadata dictionary.
        """
        playlist_id = extract_playlist_id(self.url)
        if not playlist_id:
            raise LyricsNotFound(f"Could not extract playlist ID from URL: {self.url}")
        return self.client.get_playlist(playlist_id)
