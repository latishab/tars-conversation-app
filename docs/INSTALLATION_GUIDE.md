# Installation Guide

Quick reference for installing tars-conversation-app on Raspberry Pi.

## Prerequisites

- Raspberry Pi 4 (4GB RAM recommended)
- Raspberry Pi OS (Trixie or later)
- Python 3.10 or higher
- Internet connection

## From Dashboard (Recommended)

Once tars-daemon implements app management:

1. Open tars-daemon dashboard at `http://100.84.133.74:7860`
2. Navigate to "Apps" tab
3. Find "tars-conversation-app"
4. Click "Install" button
5. Wait for installation to complete
6. Configure API keys in `.env.local`
7. Adjust settings in `config.ini` if needed
8. Click "Run" to start

## Manual Installation (SSH)

### Step 1: Clone Repository

```bash
ssh tars-pi
cd ~
git clone https://github.com/latishab/tars-conversation-app.git
cd tars-conversation-app
```

### Step 2: Run Installer

```bash
bash install.sh
```

The installer will:
- Check Python version (requires 3.10+)
- Install system dependencies (portaudio, ffmpeg)
- Create Python virtual environment
- Install all Python packages
- Create config files from templates

This takes 5-10 minutes on first run.

### Step 3: Configure

Edit API keys:
```bash
nano .env.local
```

Add your keys:
```bash
DEEPINFRA_API_KEY=your_key_here
SPEECHMATICS_API_KEY=your_key_here
# or
DEEPGRAM_API_KEY=your_key_here
```

Edit settings (optional):
```bash
nano config.ini
```

### Step 4: Run

Activate virtual environment:
```bash
source venv/bin/activate
```

Run in robot mode:
```bash
python tars_bot.py
```

Or run dashboard:
```bash
python ui/app.py
```

## Verification

Check installation:
```bash
# Activate venv
source ~/tars-conversation-app/venv/bin/activate

# Test imports
python -c "import pipecat; print('Pipecat OK')"
python -c "from tars_sdk import TarsClient; print('TARS SDK OK')"

# Test daemon connection
python -c "
import grpc
from tars_sdk import TarsClient
channel = grpc.insecure_channel('localhost:50051')
client = TarsClient(channel)
print('Daemon connection OK')
"
```

## Uninstallation

From dashboard:
1. Navigate to "Apps" tab
2. Find "tars-conversation-app"
3. Click "Uninstall" button
4. Choose whether to keep data/config

Manual:
```bash
cd ~/tars-conversation-app
bash uninstall.sh
```

## Troubleshooting

### Installation fails

Check Python version:
```bash
python3 --version
# Should be 3.10 or higher
```

Check disk space:
```bash
df -h
# Need at least 2GB free
```

Check internet:
```bash
ping google.com
```

### Dependencies fail to install

Update package lists:
```bash
sudo apt-get update
sudo apt-get upgrade
```

Reinstall system deps:
```bash
sudo apt-get install -y portaudio19-dev ffmpeg build-essential python3-dev
```

### Virtual environment issues

Remove and recreate:
```bash
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration not found

Recreate from templates:
```bash
cp config.ini.example config.ini
cp env.example .env.local
```

### Cannot connect to daemon

Check daemon is running:
```bash
systemctl status tars-daemon
```

Test gRPC port:
```bash
nc -zv localhost 50051
```

Check logs:
```bash
journalctl -u tars-daemon -f
```

## Running in Background

Use systemd service:

```bash
# Create service file
sudo nano /etc/systemd/system/tars-conversation.service
```

Add:
```ini
[Unit]
Description=TARS Conversation App
After=network.target tars-daemon.service
Requires=tars-daemon.service

[Service]
Type=simple
User=mac
WorkingDirectory=/home/mac/tars-conversation-app
ExecStart=/home/mac/tars-conversation-app/venv/bin/python tars_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable tars-conversation.service
sudo systemctl start tars-conversation.service
```

Check status:
```bash
sudo systemctl status tars-conversation.service
journalctl -u tars-conversation.service -f
```

## Updating

Pull latest changes:
```bash
cd ~/tars-conversation-app
git pull
```

Update dependencies:
```bash
source venv/bin/activate
pip install -r requirements.txt --upgrade
```

Restart if running as service:
```bash
sudo systemctl restart tars-conversation.service
```

## Resource Usage

Expected resource usage on Pi 4:

- **Installation size**: ~1.5GB (venv + packages)
- **Memory**: 500MB-1GB during conversation
- **CPU**: 30-50% (varies with STT/TTS)
- **Network**: ~100kbps for audio + API calls

Recommend:
- 4GB RAM Pi (2GB may struggle)
- Active cooling for sustained use
- Wired ethernet for stability
