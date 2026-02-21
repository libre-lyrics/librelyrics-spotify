"""Spotify lyrics module implementation.

This is the main LyricsModule implementation for Spotify.
Handles track, album, and playlist URLs.
"""
from __future__ import annotations

import logging
import re
from typing import ClassVar

from librelyrics.exceptions import ConfigurationError, LyricsNotFound
from librelyrics.models import LyricsLine, LyricsResponse
from librelyrics.modules.base import (LyricsModule, LyricsType,
                                      ModuleCapability, ModuleMeta)
from spotify.api import (SpotifyClient, extract_album_id, extract_playlist_id,
                         extract_track_id)

logger = logging.getLogger('librelyrics.modules.spotify')


class SpotifyModule(LyricsModule):
    """Spotify lyrics provider module.
    
    Fetches lyrics from Spotify's internal color-lyrics API.
    Supports track, album, and playlist URLs.
    """
    
    META: ClassVar[ModuleMeta] = ModuleMeta(
        name="Spotify",
        regex=re.compile(r"(open\.)?spotify\.com/(track|album|playlist)/"),
        requires_auth=True,
        description="Fetch lyrics from Spotify",
        lyrics_types=frozenset({LyricsType.PLAIN, LyricsType.SYNCED}),
        capabilities=frozenset({
            ModuleCapability.SINGLE_TRACK,
            ModuleCapability.ALBUM,
            ModuleCapability.PLAYLIST,
        }),
        config_schema={
            'sp_dc': 'Spotify sp_dc cookie (see README)',
            'synced_lyrics': 'Prefer synced lyrics (true/false)',
        },
    )
    LIBRELYRICS_API_VERSION: ClassVar[int] = 1
    
    def __init__(self, url: str, config: dict) -> None:
        super().__init__(url, config)
        self._client: SpotifyClient | None = None
    
    def _ensure_client(self) -> None:
        """Ensure Spotify client is initialized with current config."""
        sp_dc = self.config.get('sp_dc')
        if not sp_dc:
            raise ConfigurationError(
                "Spotify plugin requires 'sp_dc' in configuration. "
                "Run 'librelyrics --config' to set it up."
            )
        
        if self._client is None:
            self._client = SpotifyClient(sp_dc)
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
    
    def fetch(self) -> LyricsResponse:
        """Fetch lyrics for the configured URL.
        
        Returns:
            LyricsResponse with lyrics data.
            
        Raises:
            LyricsNotFound: If lyrics are not available.
        """
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
