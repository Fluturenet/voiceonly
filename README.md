# VoiceOnly

VoiceOnly converts YouTube channels into private podcast feeds. It downloads channel audio, stores metadata in MongoDB, and exposes RSS feeds you can subscribe to from any podcast app.

## What it does

- Monitors one or more YouTube channels on a schedule
- Downloads audio tracks with yt-dlp (Opus output)
- Generates private RSS feeds compatible with podcast clients
- Provides a web dashboard for channel management and manual scans

## Core dependencies

- Python 3.10+
- MongoDB 5.0+
- FFmpeg
- Deno 2.0+ (required by yt-dlp JavaScript challenge solving)

Python package dependencies are listed in `requirements.txt`.

## Quick start

1. Follow the installation steps in [INSTALL.md](INSTALL.md).
2. Run the app.
3. Open the admin dashboard and add channels.

## Configuration

Main settings are defined in `.env` (copy from `.env.example`):

| Variable | Description |
|----------|-------------|
| `DEBUG_MODE` | Enables verbose logs and development mode behavior |
| `PASSWORD` | Admin dashboard password |
| `TOKEN` | Token used for authentication in API requests |
| `MONGODB_URI` | MongoDB connection string |
| `MONGODB_DB` | Database name |
| `DOWNLOAD_PATH` | Folder where audio files are saved |
| `HOST` | Bind address |
| `PORT` | Service port |
| `SCAN_INTERVAL_HOURS` | Automatic scan interval |
| `COOKIES_FILE` | Optional YouTube cookies file path |

## Usage

- Admin panel: `http://localhost:<PORT>/admin`
- Podcast feed by friendly name: `http://localhost:<PORT>/podcast/<friendly-name>.xml`
- Podcast feed by channel id: `http://localhost:<PORT>/podcast/<channel-id>.xml`

## Installation and deployment

See [INSTALL.md](INSTALL.md) for:

- Local setup
- `/opt/voiceonly` deployment
- `systemd` service setup
- Troubleshooting notes

## Disclaimer

VoiceOnly is for personal use only. Respect copyright laws and YouTube's Terms of Service. Do not redistribute downloaded content without proper authorization.

## License

MIT. See [LICENSE](LICENSE).
