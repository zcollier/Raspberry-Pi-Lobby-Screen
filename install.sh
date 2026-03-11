#!/bin/bash
#
# Installation script for Raspberry Pi Interactive Video Player
# Run with: bash install.sh
#

set -e

echo "======================================"
echo "Raspberry Pi Video Player Installer"
echo "======================================"
echo ""

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "Warning: This doesn't appear to be a Raspberry Pi."
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Install dependencies
echo "Installing dependencies..."
sudo apt-get update
sudo apt-get install -y mpv python3-pygame python3-rpi.gpio

# Create video directory
echo "Creating video directory..."
mkdir -p /home/pi/videos

# Create state directory (stores last-played video across reboots)
echo "Creating state directory..."
mkdir -p /home/pi/.config/video-player

# Install the Python script
echo "Installing video player script..."
sudo cp video-player.py /usr/local/bin/video-player.py
sudo chmod +x /usr/local/bin/video-player.py

# Install systemd service
echo "Installing systemd service..."
sudo cp video-player.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable video-player.service

echo ""
echo "======================================"
echo "Installation Complete!"
echo "======================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Copy your video files to /home/pi/videos/"
echo "   Supported formats: .mp4  .mov  .avi  .mkv  .webm"
echo "   Name one 'default.mp4' or 'default.mov' to auto-play on first boot."
echo ""
echo "2. Wire the 4 GPIO buttons (BCM pin numbering)."
echo "   Each button connects between its GPIO pin and GND."
echo "   Internal pull-ups are enabled — no external resistors needed."
echo ""
echo "   Pin 17 = EXIT  (stop video, return to menu)"
echo "   Pin 27 = PREV  (previous item in menu)"
echo "   Pin 22 = NEXT  (next item in menu)"
echo "   Pin 23 = PLAY  (play selected video)"
echo ""
echo "3. Configure HDMI to work without monitor connected:"
echo "   sudo nano /boot/firmware/config.txt"
echo "   (use /boot/config.txt on older Raspberry Pi OS)"
echo ""
echo "   Add these lines:"
echo "     hdmi_force_hotplug=1"
echo "     hdmi_drive=2"
echo ""
echo "4. Reboot:"
echo "   sudo reboot"
echo ""
echo "---"
echo "Keyboard fallback (testing without GPIO buttons):"
echo "  Up/Down arrows = navigate menu"
echo "  Enter          = play selected video"
echo "  Q              = return to menu (while playing) or quit (on menu)"
echo ""
echo "Service management:"
echo "  sudo systemctl status video-player"
echo "  sudo journalctl -u video-player -f"
echo ""
