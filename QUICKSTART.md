# Quick Start Guide

Assumes Raspberry Pi OS is already installed and you can reach the Pi. If you
are starting from a blank SD card, do `SETUP.md` first.

## Transfer Files to the Raspberry Pi

From your computer:

```bash
ssh pi@raspberrypi.local "mkdir -p /home/pi/video-player"
scp -r * pi@raspberrypi.local:/home/pi/video-player/
```

## On the Raspberry Pi

### 1. Run the installer

```bash
cd /home/pi/video-player
bash install.sh
```

This installs `mpv`, `python3-pygame`, and `python3-rpi.gpio`, creates the video
and state directories, and enables the systemd service.

### 2. Add your videos

You can copy them locally:

```bash
cp /path/to/your/video.mp4 /home/pi/videos/
```

…or just upload them to `https://www.vrhsdramaboosters.com/lobby/video/` and let
the Pi download them itself:

```bash
python3 /usr/local/bin/video-player.py --sync-now
```

After that it syncs on its own every 5 minutes.

Add as many as you like — they all show up in the on-screen menu. Supported
formats: `.mp4` `.mov` `.avi` `.mkv` `.webm`, plus images `.jpg` `.jpeg` `.png`
`.gif` `.bmp` `.webp`

Name one `default.mp4` or `default.mov` and it becomes the boot video until
someone picks a different one (after that, the player remembers the last choice).

### 3. Publish the remote state file

Upload a file to `https://www.vrhsdramaboosters.com/lobby/state.json`:

```json
{
  "version": 1,
  "video": "default.mov",
  "updated": "2026-08-12T13:00:00Z"
}
```

`video` is a bare filename that must match one of the videos you just copied.
There's a copy of this at `state.json.example`.

Then confirm the Pi can read it:

```bash
python3 /usr/local/bin/video-player.py --check-remote
```

That prints the HTTP status, caching headers, the parsed instruction, and which
local file it resolves to. If it reports a non-zero `Age` header, a CDN is
caching the file and your edits will reach the Pi late.

### 4. Wire the buttons (optional)

BCM pin numbering. Each button goes between its GPIO pin and any ground pin —
internal pull-ups are enabled, so no resistors are needed.

| BCM Pin | Button |
|---------|--------|
| 17 | EXIT — stop video, return to menu |
| 27 | PREV — previous video |
| 22 | NEXT — next video |
| 23 | PLAY — play the selected video |

Skip this for now if you just want to test: the arrow keys, Enter, and Q do the
same things from a keyboard.

### 5. Configure HDMI

```bash
# Newer Raspberry Pi OS (Bookworm and later)
sudo nano /boot/firmware/config.txt

# OR older Raspberry Pi OS
sudo nano /boot/config.txt
```

Add these two lines:

```
hdmi_force_hotplug=1
hdmi_drive=2
```

Save and exit (Ctrl+X, then Y, then Enter).

### 6. Reboot

```bash
sudo reboot
```

## That's It

The Pi boots straight into your video and checks the website every 15 seconds
for a new instruction.

To change what's playing, edit `state.json` on the website — the screen follows
within about 15 seconds. Or press the buttons in the lobby, which overrides the
website until the file changes again. Whichever happened most recently wins.

To re-assert a video after someone has overridden it locally, change the
`updated` timestamp in the JSON. Any edit counts as a new instruction.

## Testing Before Reboot (Optional)

```bash
# Start it now
sudo systemctl start video-player

# Confirm it's running
sudo systemctl status video-player

# Watch what it finds
sudo journalctl -u video-player -f

# Stop it
sudo systemctl stop video-player
```

## Adding Videos Later

Three ways, all of which need no restart:

- **Upload to the website** at `/lobby/video/` — the Pi downloads it within 5
  minutes. This is the one that needs nobody near the Pi.
- **Copy into `/home/pi/videos/`** directly, over SSH or a network share.
- **Plug in a USB drive** with videos in its root directory.

The menu picks up local changes within about 5 seconds.

If `state.json` names a file that isn't on the Pi yet, it plays the default video
and keeps waiting. Plug in the stick and it switches over on its own.

Full documentation and troubleshooting: `README.md`
