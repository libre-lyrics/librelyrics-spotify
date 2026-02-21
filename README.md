# librelyrics-spotify

Spotify lyrics provider plugin for [LibreLyrics](https://github.com/libre-lyrics/librelyrics).

## Features

- Fetch synced and unsynced lyrics from Spotify
- Support for track, album, and playlist URLs
- TOTP-based authentication with Spotify's internal API

## Installation

```bash
pip install librelyrics-spotify
```

## Configuration

Requires a Spotify `sp_dc` cookie. Set it up via:

```bash
librelyrics config edit
```

Or set it directly:

```bash
librelyrics config set plugins.Spotify.sp_dc "YOUR_SP_DC_COOKIE"
```

### Getting your `sp_dc` cookie

1. Open [Spotify Web Player](https://open.spotify.com) in your browser
2. Log in to your account
3. Open Developer Tools (F12) → Application → Cookies
4. Find the `sp_dc` cookie and copy its value

## Supported URLs

- `https://open.spotify.com/track/<id>`
- `https://open.spotify.com/album/<id>`
- `https://open.spotify.com/playlist/<id>`

## Usage

Once installed, the plugin is automatically discovered by LibreLyrics:

```bash
librelyrics "https://open.spotify.com/track/4PTG3Z6ehGkBFwjybzWkR8"
```

## License

GPL-3.0-or-later
