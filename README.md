# Raspberry Pi Auto-Playing Video Player

A simple digital signage solution that automatically plays a video file on boot via HDMI, with looping support.

## Features

- Automatically starts playing video on bootup
- Looks for `default.mp4` or `default.mov` in `/home/pi/videos/`
- Loops video continuously
- Works even if monitor is not connected at boot
- No user interaction required
- Runs as a systemd service

## Hardware Requirements

- Raspberry Pi 4
- Micro SD card with Raspberry Pi OS
- HDMI display
- Power supply

## Installation

### 1. Install Required Packages

```bash
sudo apt-get update
sudo apt-get install -y mpv
```

### 2. Create Video Directory

```bash
mkdir -p /home/pi/videos
```

### 3. Copy Your Video File

Place your video file in `/home/pi/videos/` and name it either `default.mp4` or `default.mov`:

```bash
# Example:
cp /path/to/your/video.mp4 /home/pi/videos/default.mp4
```

### 4. Install the Video Player Script

```bash
sudo cp video-player.py /usr/local/bin/video-player.py
sudo chmod +x /usr/local/bin/video-player.py
```

### 5. Install the Systemd Service

```bash
sudo cp video-player.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable video-player.service
```

### 6. Configure HDMI Output (Important!)

This ensures video plays even if monitor is not connected at boot:

```bash
sudo nano /boot/firmware/config.txt
```

Add or modify these lines:

```
# Force HDMI output
hdmi_force_hotplug=1
hdmi_drive=2
```

If you're using older Raspberry Pi OS, the config file might be at `/boot/config.txt` instead.

### 7. Reboot

```bash
sudo reboot
```

## Usage

### Start/Stop/Status

```bash
# Check status
sudo systemctl status video-player

# Start manually
sudo systemctl start video-player

# Stop
sudo systemctl stop video-player

# Restart
sudo systemctl restart video-player

# View logs
sudo journalctl -u video-player -f
```

### Changing the Video

1. Stop the service: `sudo systemctl stop video-player`
2. Replace the video file in `/home/pi/videos/`
3. Start the service: `sudo systemctl start video-player`

Or simply replace the file and reboot.

## Troubleshooting

### Video not playing

```bash
# Check service status
sudo systemctl status video-player

# View detailed logs
sudo journalctl -u video-player -n 50

# Test manually
mpv --loop --no-audio --fullscreen /home/pi/videos/default.mp4
```

### No HDMI output

- Ensure `hdmi_force_hotplug=1` is set in `/boot/firmware/config.txt` (or `/boot/config.txt`)
- Check HDMI cable connection
- Try a different HDMI port on the Pi 4 (it has 2 micro HDMI ports)

### Audio issues

The default configuration plays video without audio. To enable audio, edit `video-player.py` and remove the `--no-audio` flag.

## Customization

### Video Directory

To change the video directory, edit both:
- `/usr/local/bin/video-player.py` - update the `VIDEO_DIR` variable
- `/etc/systemd/system/video-player.service` - update the `WorkingDirectory`

### Supported Formats

mpv supports many video formats including:
- MP4 (.mp4)
- MOV (.mov)
- AVI (.avi)
- MKV (.mkv)
- WebM (.webm)

To support additional file extensions, edit the `VIDEO_FILES` list in `video-player.py`.
