# Installation Guide

This document covers local installation, production-style deployment in `/opt/voiceonly`, and basic troubleshooting.

## Prerequisites

- Python 3.10+
- MongoDB 5.0+
- FFmpeg
- Deno 2.0+

Install Deno (example):

```bash
curl -fsSL https://deno.land/x/install/install.sh | sh
```

Verify:

```bash
deno --version
```

## Local setup

1. Clone the repository:

```bash
git clone https://github.com/yourusername/voiceonly.git
cd voiceonly
```

2. Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install Python dependencies:

```bash
pip install -U pip
pip install -r requirements.txt
```

4. Create your environment file:

```bash
cp .env.example .env
```

5. Edit `.env` with your values.

6. Make sure MongoDB is running.

7. Start the application:

```bash
python -m app.main
```

Default URLs:

- App: `http://localhost:8000`
- Admin: `http://localhost:8000/admin`

## Deploy to `/opt/voiceonly` with systemd

1. Copy project files:

```bash
sudo mkdir -p /opt/voiceonly
sudo cp -r . /opt/voiceonly
sudo chown -R $USER:$USER /opt/voiceonly
```

2. Install dependencies in `/opt/voiceonly`:

```bash
cd /opt/voiceonly
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

3. Ensure `/opt/voiceonly/.env` exists and is configured.

4. Install service unit:

Edit voiceonly.service

```bash
sudo cp /opt/voiceonly/voiceonly.service /etc/systemd/system/
```

5. Reload and start service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable voiceonly.service
sudo systemctl start voiceonly.service
sudo systemctl status voiceonly.service
```

6. If MongoDB runs as a local system service:

```bash
sudo systemctl enable mongod --now
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG_MODE` | `False` | Enable debug mode |
| `PASSWORD` | `changeme` | Admin dashboard password |
| `TOKEN` | `123AB567` | Token used for authentication in API requests |
| `MONGODB_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGODB_DB` | `voiceonly` | Database name |
| `DOWNLOAD_PATH` | `./downloads` | Download folder path |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | HTTP port |
| `SCAN_INTERVAL_HOURS` | `6` | Scheduled scan interval |
| `COOKIES_FILE` | _(optional)_ | YouTube cookies file path |

## Troubleshooting

### MongoDB connection errors

- Verify MongoDB is running
- Check `MONGODB_URI` and credentials

### YouTube 403/429 errors

- Add `COOKIES_FILE`
- Increase `SCAN_INTERVAL_HOURS`
- Verify Deno installation

### Permission errors

- Check write access to `DOWNLOAD_PATH`
- Fix ownership if needed

### Service logs

```bash
journalctl -u voiceonly.service -f
```