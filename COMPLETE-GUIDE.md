# Complete Setup Guide - Overview

This document provides a complete overview of the entire process from blank SD card to working digital signage.

## Complete Process Summary

```
Blank SD Card → Install OS → First Boot → System Update → Transfer Files → Install Video Player → Add Video → Configure HDMI → Reboot → Done!
```

## Timeline Estimate

- **OS Installation:** 10-15 minutes
- **First boot & updates:** 10-20 minutes
- **File transfer & installation:** 5 minutes
- **Configuration & testing:** 5-10 minutes
- **Total:** ~45 minutes

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
3. Copy video file: `cp video.mp4 /home/pi/videos/default.mp4`

**Tools needed:** Your video file

---

### Phase 4: Configure & Deploy

**File:** `QUICKSTART.md` (Step 5-6)

1. Edit boot config: `sudo nano /boot/firmware/config.txt`
2. Add HDMI force settings:
   ```
   hdmi_force_hotplug=1
   hdmi_drive=2
   ```
3. Reboot: `sudo reboot`

**Result:** Video starts playing automatically on boot!

---

### Phase 5: Final Deployment (optional)

Once everything works:

1. Disconnect keyboard (no longer needed)
2. Can disconnect monitor temporarily (video will still play)
3. Mount Raspberry Pi in final location
4. Connect to display via HDMI
5. Power on

The video will play automatically every time the Pi powers on.

---

## Quick Reference: File Locations

| Purpose | Location |
|---------|----------|
| Video files | `/home/pi/videos/` |
| Your video must be named | `default.mp4` or `default.mov` |
| Python script | `/usr/local/bin/video-player.py` |
| Service file | `/etc/systemd/system/video-player.service` |
| Boot config | `/boot/firmware/config.txt` (or `/boot/config.txt`) |

## Quick Reference: Commands

```bash
# Check if video player is running
sudo systemctl status video-player

# Stop video player
sudo systemctl stop video-player

# Start video player
sudo systemctl start video-player

# View logs
sudo journalctl -u video-player -f

# Replace video file
sudo systemctl stop video-player
cp new-video.mp4 /home/pi/videos/default.mp4
sudo systemctl start video-player
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

## Support & Troubleshooting

### Common Issues

**Video not playing:**
```bash
sudo journalctl -u video-player -n 50
```

**No HDMI output:**
- Check `/boot/firmware/config.txt` has `hdmi_force_hotplug=1`
- Try both HDMI ports on the Pi 4

**Can't find video file:**
- Check filename is exactly `default.mp4` or `default.mov`
- Check it's in `/home/pi/videos/` directory
- Check file permissions: `ls -la /home/pi/videos/`

**Service won't start:**
```bash
# Check for errors
sudo systemctl status video-player

# Test manually
mpv --loop --fullscreen /home/pi/videos/default.mp4
```

## Production Deployment Checklist

- [ ] OS installed and updated
- [ ] Video player installed via `install.sh`
- [ ] Video file copied to `/home/pi/videos/default.mp4`
- [ ] HDMI force settings added to config.txt
- [ ] Service enabled: `sudo systemctl is-enabled video-player`
- [ ] Tested: Video plays on boot
- [ ] Tested: Video loops continuously
- [ ] Tested: Works without monitor connected at boot
- [ ] Optional: Disable WiFi if not needed (save power)
- [ ] Optional: Set up SSH key authentication for remote access

## Next Steps

1. Start with `SETUP.md` for initial Raspberry Pi setup
2. Then follow `QUICKSTART.md` for video player installation
3. Refer to `README.md` for detailed documentation and troubleshooting

Enjoy your automated digital signage system!
