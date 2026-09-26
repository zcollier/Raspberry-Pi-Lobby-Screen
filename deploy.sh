#!/bin/bash
#
# Install the player files copied into /home/pi/video-player/ (e.g. over SMB)
# and restart the player. Launched from the "Deploy Video Player" desktop icon.
#
# Refuses to install a video-player.py that doesn't compile, so a half-copied
# or broken file never replaces the working one.

SRC=/home/pi/video-player

finish() {
    echo ""
    read -r -p "Press Enter to close this window..."
    exit "$1"
}

echo "Checking $SRC/video-player.py..."
if ! python3 -m py_compile "$SRC/video-player.py"; then
    echo ""
    echo "ERROR: video-player.py has errors. Nothing was installed."
    finish 1
fi

echo "Installing video-player.py..."
sudo cp "$SRC/video-player.py" /usr/local/bin/video-player.py || finish 1
sudo chmod +x /usr/local/bin/video-player.py

# The service file only needs installing (and a daemon-reload) when it changed.
if ! cmp -s "$SRC/video-player.service" /etc/systemd/system/video-player.service; then
    echo "Installing updated video-player.service..."
    sudo cp "$SRC/video-player.service" /etc/systemd/system/ || finish 1
    sudo systemctl daemon-reload
fi

echo "Restarting the player..."
sudo systemctl restart video-player
sleep 3

echo ""
if systemctl is-active --quiet video-player; then
    echo "Player is running. Recent log:"
    echo ""
    journalctl -u video-player -n 8 --no-pager -o cat
    # Success: close on our own. Errors below keep the window open to be read.
    echo ""
    echo "Closing in 5 seconds..."
    sleep 5
    exit 0
else
    echo "ERROR: the player did not start. Recent log:"
    echo ""
    journalctl -u video-player -n 20 --no-pager -o cat
    finish 1
fi
