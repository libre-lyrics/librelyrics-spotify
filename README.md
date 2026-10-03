# librelyrics-spotify

Spotify lyrics provider plugin for [LibreLyrics](https://github.com/libre-lyrics/librelyrics).

Implements the **API version 2** plugin interface (`LIBRELYRICS_API_VERSION = 2`). It does not work with API 1 versions of LibreLyrics.

## Features

- Fetch synced and unsynced lyrics from Spotify's color-lyrics endpoint
- **Track, album, and playlist** URLs, fully paginated
- **Metadata search** by artist and title, so the plugin works with `--from spotify` and `search_priority`
- **Metadata resolution** from a track URL, so Spotify URLs can feed a different lyrics provider
- TOTP-based authentication against Spotify's internal Partner API
- Rate-limit aware: classifies failures and lets the core handle back-off

## Requirements

- LibreLyrics **1.2.0+** (API version 2)
- Python 3.10+

## Installation

```bash
pip install librelyrics-spotify
```

The plugin registers itself through the `librelyrics.plugins` entry point, so LibreLyrics discovers it automatically:

```bash
librelyrics plugin list
```

## Configuration

Requires a Spotify `sp_dc` cookie. The TOTP secret dictionary URL has a built-in default, and you can override it in configuration if that source is blocked in your environment. The configured value takes priority when set.

The config section is keyed by the plugin name **in lower case** — `plugins.spotify`, not `plugins.Spotify`. A value written under the wrong case is silently ignored.

```bash
librelyrics config set plugins.spotify.sp_dc "YOUR_SP_DC_COOKIE"

# Optional: override the TOTP secret source if the default is blocked
librelyrics config set plugins.spotify.totp_secret_cipher_dict_url "https://example.com/secretDict.json"
```

Or set it up interactively:

```bash
librelyrics config edit
```

### Config keys

| Key | Required | Description |
|---|---|---|
| `sp_dc` | Yes | Spotify `sp_dc` cookie used to authenticate against the internal API. |
| `totp_secret_cipher_dict_url` | No | Override for the TOTP secret dictionary URL. Defaults to the built-in public source. |

### Getting your `sp_dc` cookie

1. Open [Spotify Web Player](https://open.spotify.com) in your browser
2. Log in to your account
3. Open Developer Tools (F12) → Application → Cookies
4. Find the `sp_dc` cookie and copy its value

## Supported URLs

- `https://open.spotify.com/track/<id>`
- `https://open.spotify.com/album/<id>`
- `https://open.spotify.com/playlist/<id>`
- Localized paths (`/intl-de/track/<id>`) and `spotify:track:<id>` URIs

## Capabilities

Declared in `META.capabilities`:

| Capability | Effect |
|---|---|
| `SINGLE_TRACK` | Fetches lyrics for a track URL |
| `ALBUM` | Expands an album URL into per-track fetches |
| `PLAYLIST` | Expands a playlist URL into per-track fetches |
| `SEARCH` | Finds a track by artist and title |
| `RESOLVE` | Fills artist, title, album, and duration from a track URL |

Lyrics types: `PLAIN` and `SYNCED` (line-synced). Word-level (rich synced) lyrics are not exposed by Spotify.

## Usage

Once installed, the plugin is automatically discovered by LibreLyrics:

```bash
# Track
librelyrics "https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8"

# Album or playlist (paginated; tracks are fetched in parallel)
librelyrics "https://open.spotify.com/album/..."
librelyrics "https://open.spotify.com/playlist/..."

# Search by metadata through this plugin
librelyrics --artist "Artist" --title "Track" --from spotify

# Use Spotify only to resolve metadata, then fetch lyrics elsewhere
librelyrics "https://open.spotify.com/track/..." --from applemusic

# Spotify lyrics only, bypassing any search_priority list
librelyrics "https://open.spotify.com/track/..." --direct
```

To prefer Spotify in a multi-plugin setup:

```bash
librelyrics config set search_priority spotify,applemusic
```

## Error Handling

The plugin classifies provider responses and lets the core apply back-off:

| Condition | Exception | Retried |
|---|---|---|
| HTTP 404 (no lyrics) | `LyricsNotFound` | No |
| HTTP 429 | `RateLimitError` (honours `Retry-After`) | Yes |
| HTTP 5xx / connection error | `TransientProviderError` | Yes |
| HTTP 401 | Token dropped, `TransientProviderError` so a fresh token is fetched | Yes |
| Other rejections | `ProviderError` | No |

Only a 404 is reported as "no lyrics" — a rejected request is never disguised as an empty download.

## Library Use

```python
from librelyrics import TrackQuery
from spotify import SpotifyModule

query = TrackQuery(url="https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8")
plugin = SpotifyModule(query, {"sp_dc": "YOUR_SP_DC_COOKIE"})

response = plugin.fetch_with_retry()
print(response.synced, response.to_lrc())
```

In normal use you do not instantiate the plugin directly — `LibreLyrics` loads it from the entry point and merges `plugins.spotify` config for you.

## License

GPL-3.0-or-later