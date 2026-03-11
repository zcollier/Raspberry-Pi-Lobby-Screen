# Quick Start Guide

## Transfer Files to Raspberry Pi

1. Copy all files to your Raspberry Pi:

```bash
scp -r * pi@raspberrypi.local:/home/pi/video-player/
```

## On the Raspberry Pi

2. Navigate to the directory:

```bash
cd /home/pi/video-player
```

3. Run the installer:

```bash
bash install.sh
```

4. Copy your video file:

```bash
cp /path/to/your/video.mp4 /home/pi/videos/default.mp4
```

5. Configure HDMI (choose the correct path for your system):

```bash
# For newer Raspberry Pi OS (Bookworm and later)
sudo nano /boot/firmware/config.txt

# OR for older Raspberry Pi OS
sudo nano /boot/config.txt
```

Add these two lines:

```
hdmi_force_hotplug=1
hdmi_drive=2
```

Save and exit (Ctrl+X, then Y, then Enter).

6. Reboot:

```bash
sudo reboot
```

## That's it!

Your video should now start playing automatically when the Raspberry Pi boots up.

## Testing Before Reboot (Optional)

To test manually before rebooting:

```bash
sudo systemctl start video-player
```

Check if it's working:

```bash
sudo systemctl status video-player
```

Stop it:

```bash
sudo systemctl stop video-player
```
