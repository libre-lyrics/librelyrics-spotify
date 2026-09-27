"""Tests for the Spotify plugin — API v2 compliance & functionality."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from librelyrics.exceptions import ConfigurationError, LyricsNotFound
from librelyrics.models import LyricsLine, TrackQuery
from librelyrics.modules.base import (
    LIBRELYRICS_API_VERSION,
    ModuleCapability,
    LyricsType,
)

from spotify.module import SpotifyModule
from spotify.api import (
    SpotifyClient,
    extract_album_id,
    extract_playlist_id,
    extract_track_id,
)


class TestSpotifyApiV2:
    """Verify the Spotify plugin satisfies LibreLyrics API v2 requirements."""

    def test_api_version_is_2(self):
        assert SpotifyModule.LIBRELYRICS_API_VERSION == LIBRELYRICS_API_VERSION == 2

    def test_meta_has_id(self):
        assert hasattr(SpotifyModule.META, "id")
        assert SpotifyModule.META.id == "spotify"

    def test_meta_id_is_lowercase_alphanumeric(self):
        assert SpotifyModule.META.id.isalnum()
        assert SpotifyModule.META.id == SpotifyModule.META.id.lower()

    def test_constructor_accepts_track_query(self):
        """v2 constructor must accept (query: TrackQuery, config: dict)."""
        query = TrackQuery(url="https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8")
        module = SpotifyModule(query=query, config={})
        assert module.query is query

    def test_url_property_delegates_to_query(self):
        url = "https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8"
        module = SpotifyModule(query=TrackQuery(url=url), config={})
        assert module.url == url

    def test_url_property_returns_none_when_no_url(self):
        module = SpotifyModule(query=TrackQuery(url=None), config={})
        assert module.url is None

    def test_has_single_track_capability(self):
        assert SpotifyModule.has_capability(ModuleCapability.SINGLE_TRACK)

    def test_has_album_capability(self):
        assert SpotifyModule.has_capability(ModuleCapability.ALBUM)

    def test_has_playlist_capability(self):
        assert SpotifyModule.has_capability(ModuleCapability.PLAYLIST)

    def test_has_resolve_capability(self):
        assert SpotifyModule.has_capability(ModuleCapability.RESOLVE)

    def test_has_search_capability(self):
        assert SpotifyModule.has_capability(ModuleCapability.SEARCH)

    def test_matches_artist_title_without_url(self):
        assert (
            SpotifyModule.matches(TrackQuery(artist="Ed Sheeran", title="Perfect"))
            is True
        )

    def test_requires_auth(self):
        assert SpotifyModule.META.requires_auth is True

    def test_supports_plain_and_synced(self):
        assert LyricsType.PLAIN in SpotifyModule.META.lyrics_types
        assert LyricsType.SYNCED in SpotifyModule.META.lyrics_types

    def test_matches_track_url(self):
        query = TrackQuery(url="https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8")
        assert SpotifyModule.matches(query) is True

    def test_matches_album_url(self):
        query = TrackQuery(url="https://open.spotify.com/album/2S8ZSnpmlReMfteHNp3zju")
        assert SpotifyModule.matches(query) is True

    def test_matches_playlist_url(self):
        query = TrackQuery(
            url="https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        )
        assert SpotifyModule.matches(query) is True

    def test_does_not_match_unrelated_url(self):
        query = TrackQuery(url="https://music.apple.com/us/song/test/123")
        assert SpotifyModule.matches(query) is False

    def test_default_config_has_sp_dc(self):
        cfg = SpotifyModule.default_config()
        assert "sp_dc" in cfg
        assert "synced_lyrics" in cfg

    def test_config_schema_has_sp_dc(self):
        assert "sp_dc" in SpotifyModule.META.config_schema


# ---------------------------------------------------------------------------
# URL Extraction Tests
# ---------------------------------------------------------------------------


def test_extract_track_id() -> None:
    assert (
        extract_track_id("https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8")
        == "4PTG3Z6ehGkBFwjybzWkR8"
    )
    assert (
        extract_track_id(
            "https://open.spotify.com/intl-ja/track/4PTG3Z6ehGkBFwjybzWkR8?si=123"
        )
        == "4PTG3Z6ehGkBFwjybzWkR8"
    )
    assert (
        extract_track_id("spotify:track:4PTG3Z6ehGkBFwjybzWkR8")
        == "4PTG3Z6ehGkBFwjybzWkR8"
    )
    assert (
        extract_track_id("https://open.spotify.com/album/4PTG3Z6ehGkBFwjybzWkR8")
        is None
    )
    assert extract_track_id("invalid") is None


def test_extract_album_id() -> None:
    assert (
        extract_album_id("https://open.spotify.com/album/6akEvsycV25SeWFetPf5Zu")
        == "6akEvsycV25SeWFetPf5Zu"
    )
    assert (
        extract_album_id(
            "https://open.spotify.com/intl-de/album/6akEvsycV25SeWFetPf5Zu?si=xyz"
        )
        == "6akEvsycV25SeWFetPf5Zu"
    )
    assert (
        extract_album_id("spotify:album:6akEvsycV25SeWFetPf5Zu")
        == "6akEvsycV25SeWFetPf5Zu"
    )
    assert (
        extract_album_id("https://open.spotify.com/track/6akEvsycV25SeWFetPf5Zu")
        is None
    )


def test_extract_playlist_id() -> None:
    assert (
        extract_playlist_id("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
        == "37i9dQZF1DXcBWIGoYBM5M"
    )
    assert (
        extract_playlist_id("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M")
        == "37i9dQZF1DXcBWIGoYBM5M"
    )
    assert (
        extract_playlist_id("https://open.spotify.com/track/37i9dQZF1DXcBWIGoYBM5M")
        is None
    )


# ---------------------------------------------------------------------------
# Validation & Fetch Logic Tests
# ---------------------------------------------------------------------------


def test_validate_config_missing_sp_dc() -> None:
    with pytest.raises(ConfigurationError):
        SpotifyModule.validate_config({})


def test_validate_config_valid_sp_dc() -> None:
    SpotifyModule.validate_config({"sp_dc": "valid_cookie"})


def test_fetch_raises_without_sp_dc() -> None:
    module = SpotifyModule(
        query=TrackQuery(url="https://open.spotify.com/track/123"), config={}
    )
    with pytest.raises(ConfigurationError):
        module._fetch_track_lyrics("123")


def test_totp_init_accepts_custom_url() -> None:
    from spotify.totp import TOTP

    with patch("spotify.totp.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {"v1": [0, 1, 2]}
        totp = TOTP(secret_cipher_dict_url="https://example.com/custom_secret.json")
        assert totp.secret_cipher_dict_url == "https://example.com/custom_secret.json"
        mock_get.assert_called_once_with(
            "https://example.com/custom_secret.json", timeout=10
        )


def test_resolve_track() -> None:
    module = SpotifyModule(
        query=TrackQuery(url="https://open.spotify.com/track/123"), config={}
    )
    mock_client = MagicMock()
    mock_client.get_track.return_value = {
        "name": "Test Track",
        "artists": [{"name": "Test Artist"}],
        "album": {"name": "Test Album"},
        "duration_ms": 180000,
    }
    module._client = mock_client
    resolved = module.resolve()
    assert resolved.title == "Test Track"
    assert resolved.artist == "Test Artist"
    assert resolved.album == "Test Album"
    assert resolved.duration_ms == 180000


def test_list_tracks_album() -> None:
    module = SpotifyModule(
        query=TrackQuery(url="https://open.spotify.com/album/456"), config={}
    )
    mock_client = MagicMock()
    mock_client.get_album.return_value = {
        "name": "Album Name",
        "tracks": [
            {
                "id": "t1",
                "name": "Song 1",
                "artists": [{"name": "Artist 1"}],
                "duration_ms": 120000,
            },
            {
                "id": "t2",
                "name": "Song 2",
                "artists": [{"name": "Artist 2"}],
                "duration_ms": 130000,
            },
        ],
    }
    module._client = mock_client
    tracks = module.list_tracks()
    assert len(tracks) == 2
    assert tracks[0].title == "Song 1"
    assert tracks[0].artist == "Artist 1"
    assert tracks[0].album == "Album Name"
    assert tracks[0].url == "https://open.spotify.com/track/t1"
    assert tracks[1].title == "Song 2"


def test_list_tracks_playlist() -> None:
    module = SpotifyModule(
        query=TrackQuery(url="https://open.spotify.com/playlist/789"), config={}
    )
    mock_client = MagicMock()
    mock_client.get_playlist.return_value = {
        "name": "Playlist Name",
        "tracks": {
            "items": [
                {
                    "id": "p1",
                    "name": "Play Song 1",
                    "artists": [{"name": "Artist A"}],
                    "album": {"name": "Alb A"},
                    "duration_ms": 100000,
                }
            ]
        },
    }
    module._client = mock_client
    tracks = module.list_tracks()
    assert len(tracks) == 1
    assert tracks[0].title == "Play Song 1"
    assert tracks[0].artist == "Artist A"


def test_fetch_without_url_uses_search() -> None:
    module = SpotifyModule(
        query=TrackQuery(artist="Ed Sheeran", title="Perfect"),
        config={"sp_dc": "cookie", "synced_lyrics": True},
    )
    mock_client = MagicMock()
    mock_client.search.return_value = {"tracks": {"items": [{"id": "found123"}]}}
    mock_client.get_track.return_value = {
        "name": "Perfect",
        "artists": [{"name": "Ed Sheeran"}],
        "album": {"name": "Divide", "id": "alb"},
        "duration_ms": 263000,
        "explicit": False,
        "track_number": 5,
    }
    mock_client.get_lyrics.return_value = {
        "lyrics": {
            "syncType": "UNSYNCED",
            "lines": [{"words": "I found a love"}],
        }
    }
    module._client = mock_client
    response = module.fetch()
    mock_client.search.assert_called_once()
    mock_client.get_lyrics.assert_called_once_with("found123")
    assert response.title == "Perfect"
    assert response.source == "Spotify"


def _offline_client() -> SpotifyClient:
    """SpotifyClient with tokens preset, so no TOTP/network handshake happens."""
    client = SpotifyClient.__new__(SpotifyClient)
    client.access_token = "token"
    return client


def _top_result(typename: str, data: dict) -> dict:
    return {
        "__typename": "TopResultHit",
        "item": {"__typename": typename, "data": data},
    }


def test_search_parses_top_results_into_track_shape() -> None:
    client = _offline_client()
    client.query = MagicMock(
        return_value={
            "data": {
                "searchV2": {
                    "topResultsV2": {
                        "itemsV2": [
                            _top_result(
                                "AlbumResponseWrapper",
                                {"__typename": "Album", "id": "alb1", "name": "Album"},
                            ),
                            _top_result(
                                "TrackResponseWrapper",
                                {
                                    "__typename": "Track",
                                    "id": "4PTG3Z6ehGkBFwjybzWkR8",
                                    "name": "Never Gonna Give You Up",
                                    "artists": {
                                        "items": [
                                            {
                                                "uri": "spotify:artist:0gxyHStUsqpMadRV0Di1Qt",
                                                "profile": {"name": "Rick Astley"},
                                            }
                                        ]
                                    },
                                    "albumOfTrack": {
                                        "id": "alb2",
                                        "name": "Whenever You Need Somebody",
                                    },
                                    "duration": {"totalMilliseconds": 213573},
                                },
                            ),
                        ]
                    }
                }
            }
        }
    )

    result = client.search('track:"Never Gonna Give You Up" artist:"Rick Astley"')

    assert client.query.call_args.args[0] == "searchSuggestions"
    assert client.query.call_args.args[2] == "searchSuggestions"
    tracks = result["tracks"]["items"]
    assert [t["id"] for t in tracks] == ["4PTG3Z6ehGkBFwjybzWkR8"]
    assert tracks[0]["name"] == "Never Gonna Give You Up"
    assert tracks[0]["artists"] == [
        {"id": "0gxyHStUsqpMadRV0Di1Qt", "name": "Rick Astley"}
    ]
    assert tracks[0]["album"] == {"id": "alb2", "name": "Whenever You Need Somebody"}
    assert tracks[0]["duration_ms"] == 213573


def test_search_respects_limit_and_empty_results() -> None:
    client = _offline_client()
    client.query = MagicMock(
        return_value={
            "data": {
                "searchV2": {
                    "topResultsV2": {
                        "itemsV2": [
                            _top_result(
                                "TrackResponseWrapper",
                                {"__typename": "Track", "id": "t1", "name": "One"},
                            ),
                            _top_result(
                                "TrackResponseWrapper",
                                {"__typename": "Track", "id": "t2", "name": "Two"},
                            ),
                        ]
                    }
                }
            }
        }
    )
    assert [t["id"] for t in client.search("q", limit=1)["tracks"]["items"]] == ["t1"]

    client.query = MagicMock(
        return_value={"data": {"searchV2": {"topResultsV2": {"itemsV2": []}}}}
    )
    assert client.search("q") == {"tracks": {"items": [], "total": 0}}


def test_get_album_follows_every_page() -> None:
    client = SpotifyClient.__new__(SpotifyClient)
    client.access_token = "token"

    def album_page(offset: int) -> dict:
        return {
            "data": {
                "albumUnion": {
                    "name": "Long album",
                    "artists": {"items": [{"profile": {"name": "Artist"}}]},
                    "date": {"isoString": "2020-01-02T00:00:00Z"},
                    "label": "Label",
                    "tracksV2": {
                        "totalCount": 3,
                        "items": [
                            {
                                "track": {
                                    "uri": f"spotify:track:t{offset + i}",
                                    "name": f"Track {offset + i}",
                                    "artists": {"items": []},
                                    "duration": {"totalMilliseconds": 1000},
                                }
                            }
                            for i in range(min(2, 3 - offset))
                        ],
                    },
                }
            }
        }

    client.query = MagicMock(side_effect=[album_page(0), album_page(2)])

    album = client.get_album("alb1")

    assert [t["id"] for t in album["tracks"]] == ["t0", "t1", "t2"]
    assert album["name"] == "Long album"
    assert album["artists"] == [{"name": "Artist"}]
    assert album["release_date"] == "2020-01-02"
    assert album["total_tracks"] == 3
    assert client.query.call_count == 2
    assert client.query.call_args_list[0].args[1]["offset"] == 0
    assert client.query.call_args_list[1].args[1]["offset"] == 2


def test_get_playlist_follows_every_page() -> None:
    client = SpotifyClient.__new__(SpotifyClient)
    client.access_token = "token"

    def playlist_page(offset: int) -> dict:
        return {
            "data": {
                "playlistV2": {
                    "name": "Long playlist",
                    "description": "desc",
                    "ownerV2": {"data": {"name": "Owner"}},
                    "content": {
                        "totalCount": 3,
                        "items": [
                            {
                                "itemV2": {
                                    "data": {
                                        "uri": f"spotify:track:p{offset + i}",
                                        "name": f"Song {offset + i}",
                                        "artists": {"items": []},
                                    }
                                }
                            }
                            for i in range(min(2, 3 - offset))
                        ],
                    },
                }
            }
        }

    client.query = MagicMock(side_effect=[playlist_page(0), playlist_page(2)])

    playlist = client.get_playlist("pl1")

    assert [t["id"] for t in playlist["tracks"]["items"]] == ["p0", "p1", "p2"]
    assert playlist["name"] == "Long playlist"
    assert playlist["owner"] == {"display_name": "Owner"}
    assert playlist["tracks"]["total"] == 3
    assert client.query.call_count == 2
    assert client.query.call_args_list[0].args[1]["offset"] == 0
    assert client.query.call_args_list[1].args[1]["offset"] == 2
