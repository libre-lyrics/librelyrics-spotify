"""Spotify lyrics plugin for LibreLyrics.

Provides lyrics from Spotify using their internal API.
Requires sp_dc cookie for authentication.

Install: pip install librelyrics-spotify
"""
from spotify.module import SpotifyModule

__all__ = ['SpotifyModule']
