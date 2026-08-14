# Complete Setup Guide - Overview

This document provides a complete overview of the entire process from blank SD
card to a working, remotely-controllable lobby screen.

## Complete Process Summary

```
Blank SD Card → Install OS → First Boot → System Update → Transfer Files
    → Install Video Player → Add Videos → Publish state.json → Wire Buttons
    → Configure HDMI → Reboot → Done!
```

## Timeline Estimate

- **OS Installation:** 10-15 minutes
- **First boot & updates:** 10-20 minutes
- **File transfer & installation:** 5 minutes
- **Publishing the remote state file:** 5-10 minutes
- **Button wiring:** 10-15 minutes (optional)
- **Configuration & testing:** 5-10 minutes
- **Total:** ~1 hour

## How Control Works

The Pi never accepts an inbound connection. It reaches *out* to the website
every 15 seconds and reads a small JSON file that says which video should be
playing. That is what makes this work on a network that can't accept incoming
traffic.

Two things can change what's playing, and **the most recent one wins**:

| Time | What happened | Result |
|------|---------------|--------|
| 8:00 AM | Website set to `A.mp4` | Plays A |
| 8:05 AM | Someone presses a button in the lobby, selecting `B.mp4` | Plays B |
| 8:06 AM | Poll runs; the website still says `A.mp4` | **Still plays B** |
| 9:00 AM | Website changed to `C.mp4` | Plays C |

The Pi decides this by noticing when the file *changes*, not by comparing
timestamps against its own clock — which matters, because a Raspberry Pi has no
battery-backed clock and boots up not knowing the time.

To re-assert a video after a local override, change the `updated` timestamp in
the JSON. Any edit counts as a new instruction.

---

## Detailed Steps

### Phase 1: Prepare SD Card (on your computer)

**File:** `SETUP.md` (Steps 1-2)

1. Download Raspberry Pi Imager
2. Write Raspberry Pi OS to SD card
3. Configure WiFi/SSH in advanced settings
4. Insert SD card into Raspberry Pi

**Tools needed:** Computer, SD card reader, internet

---

### Phase 2: Initial Setup (on Raspberry Pi)

**File:** `SETUP.md` (Steps 3-5)

1. First boot with monitor and keyboard connected
2. Update system: `sudo apt-get update && sudo apt-get upgrade -y`
3. Run `sudo raspi-config` to enable desktop autologin
4. Reboot

**Tools needed:** Monitor, HDMI cable, keyboard, internet

---

### Phase 3: Install Video Player (on Raspberry Pi)

**File:** `QUICKSTART.md` or `README.md`

1. Transfer video-player files to `/home/pi/video-player/`
2. Run: `bash install.sh`
3. Copy video files: `cp video.mp4 /home/pi/videos/`

**Tools needed:** Your video files

---

### Phase 4: Publish the Remote State File

**File:** `README.md` — "Remote Control"

Upload this to `https://www.vrhsdramaboosters.com/lobby/state.json`
(there's a copy at `state.json.example`):

```json
{
  "version": 1,
  "video": "default.mov",
  "updated": "2026-08-12T13:00:00Z"
}
```

Then verify the Pi can read it:

```bash
python3 /usr/local/bin/video-player.py --check-remote
```

This reports the HTTP status, caching headers, the parsed instruction, and which
local file it resolves to — without touching the display. **A non-zero `Age`
header means a CDN is caching the file**, and your edits will reach the Pi late
or not at all. That is the single most likely thing to make the system feel
broken.

---

### Phase 4b: Publish Your Media Files

**File:** `README.md` — "Media Sync"

Upload videos and images to:

```
https://www.vrhsdramaboosters.com/lobby/video/
```

The Pi mirrors that directory into `/home/pi/videos/` every 5 minutes — a new
file appears on the lobby screen without anyone touching the Pi. A file is
downloaded when it's missing locally, or when its size or timestamp differs, so
replacing `default.mov` on the website replaces it on the Pi.

Fetch everything immediately instead of waiting:

```bash
python3 /usr/local/bin/video-player.py --sync-now
```

Downloads are atomic, disk space is checked first, nothing is ever deleted, and
a file that is still uploading is detected and retried. Prefer uploading under a
temporary name and renaming when complete — Apache serves half-written files.

---

### Phase 5: Wire the Buttons (optional)

**File:** `README.md` — "Local Control"

Four momentary pushbuttons, each wired between its GPIO pin and ground
(BCM numbering, internal pull-ups enabled — no resistors needed):

| BCM Pin | Button |
|---------|--------|
| 17 | EXIT |
| 27 | PREV |
| 22 | NEXT |
| 23 | PLAY |

Skip this if the screen will be controlled only from the website — a keyboard
can drive the menu for testing.

---

### Phase 6: Configure & Deploy

**File:** `QUICKSTART.md` (Steps 5-6)

1. Edit boot config: `sudo nano /boot/firmware/config.txt`
2. Add HDMI force settings:
   ```
   hdmi_force_hotplug=1
   hdmi_drive=2
   ```
3. Reboot: `sudo reboot`

---

### Phase 7: Final Deployment

1. Disconnect the keyboard
2. Can disconnect the monitor temporarily (video will still play)
3. Mount the Raspberry Pi and any button panel in the final location
4. Connect to the display via HDMI
5. Power on

Every time the Pi powers on, it resumes whatever should be playing — including a
local override made before it lost power.

---

## Quick Reference: File Locations

| Purpose | Location |
|---------|----------|
| Remote state file | `https://www.vrhsdramaboosters.com/lobby/state.json` |
| Remote media directory | `https://www.vrhsdramaboosters.com/lobby/video/` |
| Video files (SD card) | `/home/pi/videos/` |
| Video files (USB) | Root directory of any drive under `/media/pi/` |
| Fallback filename | `default.mp4`, then `default.mov` (SD card first) |
| Persisted state | `/home/pi/.config/video-player/state.json` |
| Python script | `/usr/local/bin/video-player.py` |
| Service file | `/etc/systemd/system/video-player.service` |
| Boot config | `/boot/firmware/config.txt` (or `/boot/config.txt`) |

## Quick Reference: Controls

| BCM Pin | Button | On the menu | While playing |
|---------|--------|-------------|---------------|
| 17 | EXIT | — | Stop, return to menu |
| 27 | PREV | Selection up | Previous video |
| 22 | NEXT | Selection down | Next video |
| 23 | PLAY | Play selection | — |

Keyboard fallback: ↑↓ navigate, Enter plays, Q returns to the menu or quits.

## Quick Reference: Commands

```bash
# Check if the video player is running
sudo systemctl status video-player

# Stop / start
sudo systemctl stop video-player
sudo systemctl start video-player

# View logs
sudo journalctl -u video-player -f

# Diagnose the remote state file and preview pending media downloads
python3 /usr/local/bin/video-player.py --check-remote

# Download new or changed media files now
python3 /usr/local/bin/video-player.py --sync-now

# Add videos — no service restart needed, picked up within ~5 seconds
cp new-video.mp4 /home/pi/videos/
```

## Files in This Repository

| File | Purpose |
|------|---------|
| `SETUP.md` | Initial Raspberry Pi setup from blank SD card |
| `QUICKSTART.md` | Quick installation guide |
| `README.md` | Complete documentation |
| `COMPLETE-GUIDE.md` | This overview document |
| `video-player.py` | Main video player script |
| `video-player.service` | Systemd service configuration |
| `install.sh` | Automated installation script |
| `state.json.example` | Sample remote state file |
| `tests/` | Test suites for the precedence and fallback logic |

## Support & Troubleshooting

### Common Issues

**A website change didn't take effect:**
```bash
python3 /usr/local/bin/video-player.py --check-remote
```
Check in this order: is a cache serving a stale copy (`Age` header), is the JSON
valid, does the filename match a local file, and did someone press a button more
recently? Bump `updated` to override a local choice.

**Video not playing:**
```bash
sudo journalctl -u video-player -n 50
```

**No HDMI output:**
- Check `/boot/firmware/config.txt` has `hdmi_force_hotplug=1`
- Try both HDMI ports on the Pi 4

**Menu is empty / can't find video files:**
- Check files are directly in `/home/pi/videos/`, not in a subfolder
- Check the extension is one of `.mp4` `.mov` `.avi` `.mkv` `.webm`
- Check file permissions: `ls -la /home/pi/videos/`

**A video is marked "unplayable":**
mpv exited immediately three times in a row, so the file was quarantined to
avoid a restart loop. Usually a corrupt file or a USB drive pulled mid-playback.
Restart the service to clear it.

**Buttons do nothing:**
```bash
sudo journalctl -u video-player | grep GPIO
```
`GPIO not available` means `RPi.GPIO` is missing or inaccessible — the player
falls back to keyboard-only mode instead of failing.

**Service won't start:**
```bash
sudo systemctl status video-player
mpv --loop --fullscreen /home/pi/videos/default.mp4
```

## Production Deployment Checklist

- [ ] OS installed and updated
- [ ] Video player installed via `install.sh`
- [ ] Video files copied to `/home/pi/videos/`
- [ ] `state.json` published and reachable
- [ ] `--check-remote` reports the expected video and no caching `Age` header
- [ ] HDMI force settings added to config.txt
- [ ] Service enabled: `sudo systemctl is-enabled video-player`
- [ ] Tested: Video plays on boot
- [ ] Tested: Video loops continuously
- [ ] Tested: Works without monitor connected at boot
- [ ] Tested: Editing `state.json` changes the screen within ~15 seconds
- [ ] Tested: Uploading a file to `/lobby/video/` downloads within ~5 minutes
- [ ] Tested: Replacing a file on the website replaces it on the Pi
- [ ] Tested: Unplugging the network leaves the video playing
- [ ] Tested: All four buttons respond (if wired)
- [ ] Tested: A button press survives a power cycle
- [ ] Tested: USB drive videos appear in the menu
- [ ] Optional: Set up SSH key authentication for remote access

## Next Steps

1. Start with `SETUP.md` for initial Raspberry Pi setup
2. Then follow `QUICKSTART.md` for video player installation
3. Refer to `README.md` for detailed documentation and troubleshooting
