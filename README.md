# VoiceOnly

Convert YouTube channels to private podcasts with ease. **VoiceOnly** automatically downloads audio from YouTube channels and generates iTunes-compatible podcast feeds that you can subscribe to in any podcast app.

## Features

- 🎙️ **Automatic Channel Monitoring** - Periodically scans YouTube channels for new uploads
- 📥 **Audio Download** - Extracts high-quality audio (Opus format) from YouTube videos
- 🔖 **Podcast Feeds** - Generates standard RSS 2.0 feeds compatible with iTunes and all major podcast apps
- 🔐 **Private Podcasts** - Create personalized podcast feeds accessible via friendly URLs
- 📊 **Web Dashboard** - Intuitive admin panel for managing channels and monitoring downloads
- ⚡ **High Performance** - Optimized database queries, efficient caching, and bulk download operations
- 🛡️ **Built on Modern Stack** - FastAPI, MongoDB, yt-dlp, and APScheduler

## Prerequisites

### Required

- **Python** 3.10 or higher
- **MongoDB** 5.0 or higher (running locally or remotely)
- **Deno** 2.0.0 or higher (for JavaScript challenge solving)
- **FFmpeg** (for audio encoding)

### Installing Deno

Deno is required to solve YouTube's JavaScript challenges. Installation is simple:

```bash
curl -fsSL https://deno.land/x/install/install.sh | sh
```

Or using your package manager: `sudo apt install deno` (Ubuntu/Debian) or `brew install deno` (macOS).

Verify: `deno --version`

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/voiceonly.git
cd voiceonly
```

### 2. Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Python Dependencies

```bash
pip install -U pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env  # If available, or create manually
```

Edit `.env` with your configuration:

### 5. Deploy to /opt/voiceonly

1) Copy repository to `/opt/voiceonly` and set owner:

```bash
sudo mkdir -p /opt/voiceonly
sudo cp -r . /opt/voiceonly
sudo chown -R $USER:$USER /opt/voiceonly
```

2) Create virtualenv in `/opt/voiceonly`:

```bash
cd /opt/voiceonly
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

3) Ensure `.env` is present at `/opt/voiceonly/.env` and updated.

4) Create systemd unit (if non esiste già):

```bash
sudo cp /opt/voiceonly/voiceonly.service /etc/systemd/system/
```

5) Ricarica systemd e avvia servizio:

```bash
sudo systemctl daemon-reload
sudo systemctl enable voiceonly.service
sudo systemctl start voiceonly.service
sudo systemctl status voiceonly.service
```

6) Se usi MongoDB in sistema, assicurati sia avviato:

```bash
sudo systemctl enable mongod --now
```

7) Accedi all’app su `http://localhost:8000` e dashboard su `/admin`

```env
# Debug mode (true/false)
DEBUG_MODE=False

# Admin password (change this!)
PASSWORD=your_secure_password_here

# MongoDB Configuration
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=voiceonly

# Download paths
DOWNLOAD_PATH=./downloads

# Server Configuration
HOST=0.0.0.0
PORT=8000

# Worker settings
SCAN_INTERVAL_HOURS=6

# Optional: Path to cookies file for yt-dlp authentication
# COOKIES_FILE=/path/to/cookies.txt
```

### 5. Start MongoDB

If MongoDB is not running, start it:

```bash
# Using Docker (recommended)
docker run -d -p 27017:27017 --name mongodb mongo:latest

# Or if installed locally
mongod
```

### 6. Run the Application

```bash
python -m app.main
```

The application will start at `http://localhost:8000`. The admin panel is available at `http://localhost:8000/admin`.

## Configuration Guide

### Environment Variables

All configuration is managed through environment variables (preferably in a `.env` file):

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG_MODE` | `False` | Enable debug logging and development features |
| `PASSWORD` | `changeme` | **IMPORTANT:** Change this to a secure password for admin panel access |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection string. Can include authentication credentials: `mongodb://user:pass@host:port` |
| `MONGODB_DB` | `voiceonly` | MongoDB database name to use for storing channel and video metadata |
| `DOWNLOAD_PATH` | `./downloads` | Absolute or relative path where audio files will be saved. Directory will be created if it doesn't exist |
| `HOST` | `0.0.0.0` | Server bind address. Use `127.0.0.1` for localhost-only access |
| `PORT` | `8000` | Server port number |
| `SCAN_INTERVAL_HOURS` | `6` | Interval (in hours) between automatic channel scans. Minimum recommended: 3 hours |
| `COOKIES_FILE` | _(optional)_ | Path to a Netscape-format cookies file for authenticating with YouTube. Useful for accessing restricted content or bypassing rate limits |

### Password Security

The `PASSWORD` variable protects access to the admin panel. Change it immediately:

```env
PASSWORD=a_very_strong_password_with_numbers_123!
```

### MongoDB Authentication

If your MongoDB requires authentication:

```env
MONGODB_URI=mongodb://username:password@host:port/?authSource=admin
```

### Custom Download Location

Store downloaded audio on a different volume:

```env
DOWNLOAD_PATH=/mnt/media/voiceonly_downloads
```

### YouTube Authentication (Optional)

To download restricted content or improve YouTube rate limiting, provide a cookies file:

1. Export cookies from your browser using a tool like [Get cookies.txt](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndcbcohxjaoiyjcstpgomjolkcf)
2. Save to `~/.config/voiceonly/cookies.txt`
3. Configure in `.env`:
   ```env
   COOKIES_FILE=/home/user/.config/voiceonly/cookies.txt
   ```

## Usage

### Access the Admin Panel

1. Open your browser and navigate to `http://localhost:8000/admin`
2. Enter the password (from `PASSWORD` environment variable)
3. Click "Add Channel" to start adding YouTube channels

### Adding Channels

1. Paste the YouTube channel URL (e.g., `https://www.youtube.com/@channelname` or `https://www.youtube.com/c/ChannelName`)
2. (Optional) Set a friendly name for easy URL access
3. Click "Add"

VoiceOnly will:
- Extract channel metadata
- Start monitoring for new uploads
- Schedule automatic downloads based on `SCAN_INTERVAL_HOURS`

### Accessing Podcast Feeds

Once a channel is added, access its podcast feed at one of these URLs:

- **By friendly name** (recommended): `http://localhost:8000/podcast/channel-name.xml`
- **By MongoDB ID**: `http://localhost:8000/podcast/{mongodb_id}.xml`
- **By YouTube Channel ID**: `http://localhost:8000/podcast/{youtube_channel_id}.xml`

Subscribe to the feed URL in your favorite podcast app (Apple Podcasts, Spotify, Google Podcasts, etc.).

### Manual Scan

Manually trigger a scan of all channels:
1. Go to Admin Panel → Dashboard
2. Click "🔄 Avvia Scan Ora" button
3. Monitor progress in real-time

### Channel Management

From the dashboard you can:
- **Edit Channel** - Set friendly name and toggle active/inactive status
- **View Details** - See channel information and download statistics
- **Delete Channel** - Remove channel from monitoring (downloads are preserved)

## Architecture

### Components

- **FastAPI** - Modern async web framework
- **MongoDB** - Document database for channels and videos
- **yt-dlp** - YouTube download and extraction engine
- **APScheduler** - Background task scheduling
- **Jinja2** - Template engine for web UI

### Database Schema

**Channels Collection:**
- Channel metadata from YouTube
- Subscription status and custom friendly names
- Last scan timestamp
- Video count statistics

**Videos Collection:**
- Video metadata (title, duration, upload time)
- Download status and file paths
- Timestamp for podcast feed generation
- YouTube statistics (views, likes, comments)

### Performance Optimizations

- **Bulk Downloads** - Downloads multiple videos per channel in a single yt-dlp session
- **Database Aggregation** - Uses MongoDB aggregation pipelines to avoid N+1 queries
- **LRU Feed Cache** - Caches generated RSS feeds with configurable TTL
- **Efficient Duplicate Detection** - yt-dlp download archive prevents re-downloading

## EJS (External JavaScript Scripts) Support

VoiceOnly uses yt-dlp's EJS system to solve YouTube's JavaScript challenges. With `yt-dlp[default]` installed, everything is already configured—no additional action needed. Deno will handle challenge solving automatically.

For advanced configuration, see the [yt-dlp EJS Wiki](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

## Dependencies

### Updated Requirements

The following Python packages are required:

```
fastapi[all]>=0.104.0          # Web framework with all extras
uvicorn[standard]>=0.24.0      # ASGI server
pymongo>=4.5.0                 # MongoDB driver
motor>=3.3.0                   # Async MongoDB driver
python-dotenv>=1.0.0           # Environment variable management
yt-dlp[default]>=2024.01.00    # YouTube downloader with EJS support
yt-dlp-ejs>=2024.01.00         # EJS challenge solver scripts (in [default])
apscheduler>=3.10.4            # Background job scheduling
jinja2>=3.1.2                  # Template engine
python-multipart>=0.0.6        # Form file handling
email-validator>=2.1.0         # Email validation
requests>=2.31.0               # HTTP client
```

To install with all dependencies:

```bash
pip install -r requirements.txt
pip install yt-dlp[default]  # Includes EJS support
```

## Troubleshooting

### MongoDB Connection Issues

**Error: "Database connection failed"**
- Ensure MongoDB is running: `sudo systemctl status mongodb` or check Docker
- Verify connection string in `.env`
- Check credentials if using authentication

### YouTube Download Failures

**Error: "HTTP Error 403 or 429"**
- YouTube is rate limiting your requests
- Add a cookies file to authenticate with your YouTube account
- Increase `SCAN_INTERVAL_HOURS` to reduce request frequency
- Ensure Deno is installed for EJS challenge solving

### Deno Not Found

**Error: "deno: command not found"**
- Install Deno: https://docs.deno.com/runtime/
- Verify installation: `deno --version`
- Add Deno to PATH if necessary

### Disk Space

**Error: "No space left on device"**
- Check available disk space: `df -h`
- Increase storage capacity or configure `DOWNLOAD_PATH` to a volume with more space
- Monitor `downloads/` directory size

### Permission Errors

**Error: "Permission denied"**
- Ensure VoiceOnly process has write permissions to `DOWNLOAD_PATH`
- Check `DOWNLOAD_PATH` directory ownership: `ls -la ./downloads`
- Run with appropriate user: `sudo chown user:user ./downloads`

## Development

### Running Tests

```bash
pytest tests/
```

### Viewing Logs

Logs are written to `worker.log` and console output:

```bash
tail -f worker.log
```

### Database Inspection

Connect directly to MongoDB:

```bash
mongosh mongodb://localhost:27017/voiceonly
```

Query examples:
```javascript
// List all channels
db.channels.find()

// Count downloaded videos
db.videos.countDocuments({ downloaded: true })

// Find recent downloads
db.videos.find({ downloaded: true }).sort({ download_date: -1 }).limit(10)
```

## License

MIT License - See LICENSE file for details

## Support & Contributing

- **Issues**: Report bugs on GitHub Issues
- **Discussions**: Ask questions on GitHub Discussions
- **Contributing**: Pull requests welcome!

## Roadmap

- [ ] Automatic subtitle/description caching
- [ ] Multi-language UI support
- [ ] Playlist support
- [ ] Custom metadata editing in UI
- [ ] Docker Compose deployment
- [ ] Bandwidth monitoring and limits
- [ ] Video transcoding options

## Disclaimer

VoiceOnly is for personal use only. Respect copyright laws and YouTube's Terms of Service. Do not redistribute downloaded content without proper authorization.
