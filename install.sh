#!/bin/bash
#
# Installation script for the VRHS Lobby Screen video player
# Run with: bash install.sh
#

set -e

echo "======================================"
echo "VRHS Lobby Screen — Installer"
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

# Install dependencies. Remote polling uses only the Python standard library,
# so there is nothing to install for it.
echo "Installing dependencies..."
sudo apt-get update
sudo apt-get install -y mpv python3-pygame python3-rpi.gpio

# Create video directory
echo "Creating video directory..."
mkdir -p /home/pi/videos

# Create state directory (remembers what should be playing across reboots)
echo "Creating state directory..."
mkdir -p /home/pi/.config/video-player

# Install the Python script
echo "Installing video player script..."
sudo cp video-player.py /usr/local/bin/video-player.py
sudo chmod +x /usr/local/bin/video-player.py

# Install the diagnostic wrapper, so "lobby-check" works from anywhere
echo "Installing lobby-check helper..."
sudo cp lobby-check /usr/local/bin/lobby-check
sudo chmod +x /usr/local/bin/lobby-check

# Install systemd service
echo "Installing systemd service..."
sudo cp video-player.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable video-player.service

# Set the system timezone so logs and on-screen times read as CDT/CST
echo "Setting timezone to America/Chicago..."
sudo timedatectl set-timezone America/Chicago || \
    echo "  (could not set timezone — set it manually with raspi-config)"

# If this is an upgrade and the player is already running, restart it so the new
# code takes effect now rather than at the next reboot.
if systemctl is-active --quiet video-player; then
    echo "Restarting the running video player..."
    sudo systemctl restart video-player
fi

echo ""
echo "======================================"
echo "Installation Complete!"
echo "======================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Copy your video files to /home/pi/videos/"
echo "   Supported formats: .mp4  .mov  .avi  .mkv  .webm"
echo "   Name one 'default.mp4' or 'default.mov' — it is the fallback whenever"
echo "   the remotely requested file is missing."
echo ""
echo "2. Publish the remote state file to:"
echo "     https://www.vrhsdramaboosters.com/lobby/state.json"
echo "   See state.json.example in this directory for the format."
echo ""
echo "   Then verify the Pi can read it:"
echo "     lobby-check"
echo ""
echo "   Videos and images uploaded to /lobby/video/ download automatically"
echo "   every 5 minutes. To fetch them right now:"
echo "     lobby-check --sync"
echo ""
echo "3. Wire the 4 GPIO buttons (BCM pin numbering), if you want them."
echo "   Each button connects between its GPIO pin and GND."
echo "   Internal pull-ups are enabled — no external resistors needed."
echo ""
echo "   Pin 17 = EXIT  (stop video, return to menu)"
echo "   Pin 27 = PREV  (previous video)"
echo "   Pin 22 = NEXT  (next video)"
echo "   Pin 23 = PLAY  (play selected video)"
echo ""
echo "4. Configure HDMI to work without a monitor connected:"
echo "   sudo nano /boot/firmware/config.txt"
echo "   (use /boot/config.txt on older Raspberry Pi OS)"
echo ""
echo "   Add these lines:"
echo "     hdmi_force_hotplug=1"
echo "     hdmi_drive=2"
echo ""
echo "5. Reboot:"
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
