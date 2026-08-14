# VRHS Lobby Screen — Interactive Video Player

Digital signage for the VRHS lobby monitors. A Raspberry Pi boots straight into
a fullscreen video. You choose what plays either by **editing a JSON file on the
website** or by **pressing a button in the lobby** — whichever happened most
recently wins.

## Features

- **Remote control with no open ports** — the Pi polls a JSON file over HTTPS.
  Nothing listens for inbound connections, so it works on a locked-down network
- **Most recent instruction wins** — a remote change overrides the buttons, and a
  button press overrides the website, in whichever order they happen
- **Auto-plays on boot** and resumes whatever should be playing
- **Survives internet loss** — if the site is unreachable, the Pi keeps playing
  the last thing it was told, indefinitely
- **On-screen menu** listing every available video, with remote status
- **Four physical buttons** — EXIT / PREV / NEXT / PLAY wired to GPIO pins
- **Automatic media sync** — new and changed videos and images download from the
  website on their own, so nobody has to touch the Pi to load content
- **USB drive support** — videos on a plugged-in stick appear automatically
- **Falls back gracefully** — an unknown filename plays the default video, then
  switches to the real one the moment it appears
- **Runs as a systemd service** — starts on boot, restarts if it ever crashes
- **Keyboard fallback** for testing without buttons

## Hardware Requirements

- Raspberry Pi 4
- Micro SD card with Raspberry Pi OS (desktop version)
- HDMI display
- Power supply
- 4 momentary pushbuttons (optional — the player works fine without them)

## Installation

```bash
cd /home/pi/video-player
bash install.sh
```

The installer adds `mpv`, `python3-pygame`, and `python3-rpi.gpio`, creates
`/home/pi/videos` and the state directory, sets the system timezone to
`America/Chicago`, copies the script to `/usr/local/bin/video-player.py`, and
enables the systemd service. Remote polling uses only the Python standard
library, so it needs nothing extra.

See `SETUP.md` if you are starting from a blank SD card, or `QUICKSTART.md` for
the condensed version.

### Configure HDMI output (important)

Keeps video output alive when no monitor is connected at boot:

```bash
sudo nano /boot/firmware/config.txt   # /boot/config.txt on older releases
```

```
hdmi_force_hotplug=1
hdmi_drive=2
```

Then `sudo reboot`.

---

## Remote Control

### How it works

The Pi fetches this file every 15 seconds:

```
https://www.vrhsdramaboosters.com/lobby/state.json
```

```json
{
  "version": 1,
  "video": "spring-musical-2026.mp4",
  "updated": "2026-08-12T13:00:00Z"
}
```

| Field | Required | Meaning |
|-------|----------|---------|
| `version` | no | Schema version. Defaults to `1`. A player that doesn't recognize the version ignores the file rather than guessing |
| `video` | **yes** | Bare filename to play. No paths — just the filename as it appears in `/home/pi/videos/` or on a USB stick |
| `updated` | no | ISO 8601 timestamp. Not used for decisions (see below) — it's for humans, and it doubles as a way to force a re-apply |

There is a copy of this at `state.json.example` in this repository.

Only the connection *out* to the website is needed. The Pi never accepts an
inbound connection, so nothing has to be opened on the school's firewall.

### Which instruction wins

The rule is simply **most recent instruction wins**:

| Time | What happened | Result |
|------|---------------|--------|
| 8:00 AM | Website set to `A.mp4` | Plays A |
| 8:05 AM | Someone presses NEXT in the lobby, landing on `B.mp4` | Plays B |
| 8:06 AM | Poll runs; website still says `A.mp4` | **Still plays B** |
| 9:00 AM | Website changed to `C.mp4` | Plays C |

The 8:06 row is the important one. The Pi does *not* compare the website's
timestamp against its own clock — it remembers the last remote instruction it
already acted on, and only reacts when the file actually **changes**. That means
correctness never depends on the Pi's clock being right (it has no battery-backed
clock and reads the wrong time for the first few seconds after every boot), nor
on whoever edits the JSON remembering to update the timestamp correctly.

A local override survives reboots. If someone picks a video with the buttons, it
keeps playing across power cycles until the website changes.

**To re-assert a video that someone has overridden locally**, change the
`updated` timestamp. Any edit to the file counts as a new instruction, so
bumping the timestamp re-applies the same `video` value.

### Verify the setup

Run this on the Pi after publishing the file:

```bash
python3 /usr/local/bin/video-player.py --check-remote
```

It fetches the file once, without touching the display, and reports the HTTP
status, content type, caching headers, the parsed instruction, and which local
file it resolves to. This is the fastest way to confirm the web host serves the
file correctly.

### Caching

This is the most likely thing to make the system feel broken: you edit the JSON,
watch the lobby screen, and nothing happens.

The player defends against it by sending `Cache-Control: no-cache` and appending
a cache-busting query parameter to every request. If `--check-remote` reports a
non-zero `Age` header, a CDN is still serving a cached copy, and you'll need to
adjust the caching rules on the host.

`vrhsdramaboosters.com` is served by plain Apache with **no CDN in front of it**,
which is what makes the cache-busting fully effective today.

That said, the server sends a strikingly long cache header on everything under
`/lobby/`:

```
cache-control: max-age=172800      # two days
```

The Pi is immune to it — nothing between the Pi and the origin is caching, and
every request carries a unique query parameter — but it has two consequences
worth knowing:

1. **Don't verify your edits in a browser.** A browser will happily show you a
   two-day-old copy of `state.json` while the Pi already has the new one. Trust
   `--check-remote` instead.
2. **If a CDN is ever put in front of the site**, that header would make remote
   control unreliable in a way that's hard to diagnose.

Both are worth fixing at the source. Drop an `.htaccess` into the `lobby/`
directory:

```apache
<FilesMatch "\.(json)$">
    Header set Cache-Control "no-cache, no-store, must-revalidate"
</FilesMatch>
```

Media files can keep the long cache header — the sync compares size and
timestamp via HEAD requests, which are not affected.

### Editing the file

Any method that updates the file at that URL works — FTP, cPanel, your CMS's
file manager. The Pi only cares about the bytes it gets back.

---

## Media Sync

Any video or image you publish to

```
https://www.vrhsdramaboosters.com/lobby/video/
```

is downloaded into `/home/pi/videos/` automatically. Upload a file to the
website and it reaches the lobby screen on its own — no SSH, no USB stick, no
one standing at the Pi.

### What gets downloaded

Every file in that directory with a supported extension. Subdirectories are not
scanned, and non-media files (`.txt`, `.html`, and so on) are ignored.

A file is downloaded when:

- it isn't on the Pi yet, **or**
- its **size** differs from the local copy, **or**
- its **modification time** differs from the local copy

So replacing `default.mov` on the website with a different `default.mov`
replaces it on the Pi at the next sync. The comparison is for *difference*, not
"server is newer", so restoring an older file also propagates.

After downloading, the local file's timestamp is set to match the server's.
That's what makes the comparison stable — otherwise every file would look
changed on every pass.

### How often

Every 5 minutes by default (`SYNC_INTERVAL_SEC`), on its own thread separate
from the 15-second `state.json` polling. The two are deliberately decoupled:
each sync pass costs one directory listing plus one HEAD request per file, and
running that every 15 seconds would mean tens of thousands of requests a day
against the web host. Downloading a large video also takes minutes, and that
must never delay a state check.

If you want them in lockstep anyway, set `SYNC_INTERVAL_SEC = REMOTE_POLL_INTERVAL_SEC`.

### Download the files now

```bash
python3 /usr/local/bin/video-player.py --sync-now
```

Runs one pass in the foreground and reports what it did. Useful for the first
bulk download instead of waiting out the interval.

To preview without downloading anything, `--check-remote` lists every remote
file with its size, timestamp, and whether it would be downloaded.

### Safety properties

These matter because the Pi is unattended:

- **Downloads are atomic.** Each file is written to a hidden `.part` file and
  renamed into place only when complete, so a power cut can never leave a
  truncated video where the player would try to play it.
- **Partial uploads are detected.** If a file is still being uploaded to the
  website, its size changes mid-download; the sync notices, discards the
  attempt, and retries on the next pass. This is not hypothetical — it happened
  during testing and was caught correctly.
- **Disk space is checked first.** A download that would leave less than 1 GB
  free on the SD card is refused rather than filling the card.
- **Nothing is ever deleted.** A file removed from the website stays on the Pi.
  Set `SYNC_DELETE_REMOVED = True` if you want the Pi to mirror deletions too —
  it's off by default because deleting files on a machine you can't see should
  be a deliberate choice.
- **Failures are inert.** An unreachable server, a bad listing, or a failed
  download leaves every local file untouched and never interrupts playback.

### If the file being replaced is on screen

The player relaunches mpv automatically. Without that, mpv would keep the old
file open and the screen would keep showing the previous content even though the
new one is on disk.

A file that was quarantined as unplayable also gets a fresh chance once new
content for it arrives.

### Uploading large files

Because Apache serves a file while it is still being written, prefer uploading
under a temporary name and renaming once complete — most FTP clients can do
this. The sync detects and recovers from mid-upload files on its own, but
renaming avoids the wasted download entirely.

---

## Local Control

Buttons use **BCM pin numbering**. Wire each between its GPIO pin and any ground
pin; internal pull-ups are enabled, so no external resistors are needed.

| BCM Pin | Button | On the menu | While a video is playing |
|---------|--------|-------------|--------------------------|
| 17 | EXIT | — | Stop, return to the menu |
| 27 | PREV | Move selection up | Switch to the previous video |
| 22 | NEXT | Move selection down | Switch to the next video |
| 23 | PLAY | Play the selected video | — |

PREV and NEXT wrap around and work during playback, so "just show me the next
one" doesn't require going back to the menu.

**EXIT is an instruction too.** Pressing it means "show nothing," and the screen
stays on the menu until the website changes — it will not restart on its own.

### Keyboard fallback

| Key | Action |
|-----|--------|
| ↑ / ↓ | Navigate the menu |
| Enter | Play the selected video |
| Q | Return to the menu (while playing), or quit the app (on the menu) |

### The status line

The menu footer shows what the player is doing and why:

```
Playing: B.mp4  ·  set local 8:05 AM CDT
Remote: A.mp4  ·  set 8:00 AM CDT  ·  checked 8:06 AM CDT
```

Times display in `America/Chicago`, which resolves to CDT or CST automatically
by date.

---

## Adding Videos

### SD card

```bash
cp /path/to/your/video.mp4 /home/pi/videos/
```

Appears in the menu labeled `[SD Card]` within about 5 seconds — no restart.

### USB drive

Plug in a stick with videos in its **root directory** (subfolders are not
scanned). It shows up labeled `[USB: DRIVENAME]`.

If the website names a file that isn't present yet, the Pi plays the default and
keeps waiting — plug in the stick and it switches over automatically.

### Supported formats

**Video:** `.mp4` · `.mov` · `.avi` · `.mkv` · `.webm`
**Image:** `.jpg` · `.jpeg` · `.png` · `.gif` · `.bmp` · `.webp`

Images are treated as playable items: selecting one displays it full screen
indefinitely, which makes a poster or announcement slide work the same way a
video does. `state.json` can name an image just as it names a video.

Dot-prefixed files are ignored, which is also why in-progress downloads and
macOS `.DS_Store` files never appear in the menu.

---

## What Plays on Boot

1. Whatever the persisted state says should be playing — the normal case
2. If that file is missing, the default video
3. On a fresh install with no state, `default.mp4`, then `default.mov`, then the
   first video alphabetically

The default is looked up on the SD card first, then USB drives. Note that
**`default.mp4` takes priority over `default.mov`** if both exist.

State lives in `/home/pi/.config/video-player/state.json`. Delete it to reset the
player to a clean slate. An older `last_played.txt` is migrated automatically on
first run.

---

## Usage

```bash
# Status and logs
sudo systemctl status video-player
sudo journalctl -u video-player -f

# Start / stop / restart
sudo systemctl start video-player
sudo systemctl stop video-player
sudo systemctl restart video-player

# Check the remote state file and preview what media would sync
python3 /usr/local/bin/video-player.py --check-remote

# Download new or changed media files right now
python3 /usr/local/bin/video-player.py --sync-now
```

## Troubleshooting

### The website change didn't take effect

1. Run `--check-remote` on the Pi. It reports exactly what the Pi sees.
2. If it reports a non-zero `Age` header, a cache is serving a stale copy.
3. If it reports `INVALID`, the JSON has an error — the message says which.
4. If it reports `NOT FOUND`, the filename doesn't match any local file. Check
   spelling and extension; matching is case-insensitive but otherwise exact.
5. Remember someone may have pressed a button more recently. Bump the `updated`
   timestamp to override.

### A file on the website never arrives on the Pi

```bash
python3 /usr/local/bin/video-player.py --check-remote   # what would sync
python3 /usr/local/bin/video-player.py --sync-now       # do it now, verbosely
```

Common causes, in the order worth checking:

1. **Unsupported extension.** Only the video and image types listed above are
   downloaded.
2. **In a subdirectory.** Only the top level of `/lobby/video/` is scanned.
3. **Still uploading.** The sync refuses a file whose size changes while it is
   being fetched and retries on the next pass. `--sync-now` says so explicitly.
4. **Disk full.** A download that would leave under 1 GB free is refused. Check
   with `df -h /home/pi`.
5. **Directory listing turned off.** The sync relies on Apache's autoindex for
   `/lobby/video/`. If an `index.html` is ever placed in that directory, the
   listing disappears and the sync silently finds nothing. `--check-remote`
   reports the file count it sees.

### Remote polling never runs

```bash
sudo journalctl -u video-player | grep -i remote
```

Network failures are logged on the first failure and roughly every half hour
after that, so an overnight outage doesn't flood the journal.

### Video not playing

```bash
sudo systemctl status video-player
sudo journalctl -u video-player -n 50
mpv --loop --fullscreen /home/pi/videos/default.mp4
```

### A video shows as "unplayable" in the menu

If mpv exits within 5 seconds of launching, three times in a row, the file is
quarantined and the player falls back to the default rather than looping on a
broken file. Usually this means a corrupt file or a USB drive pulled mid-playback.
Restart the service to clear the quarantine.

### Buttons do nothing

```bash
sudo journalctl -u video-player | grep GPIO
```

`GPIO initialized.` means the pins are live. `GPIO not available` means
`RPi.GPIO` is missing or inaccessible — the app falls back to keyboard-only mode
rather than failing.

### No HDMI output

- Ensure `hdmi_force_hotplug=1` is set in `/boot/firmware/config.txt`
- Try the other micro HDMI port (HDMI0 is nearest the power port)

### Audio

Videos play **with audio**. To mute, add `--no-audio` to the `cmd` list in
`launch_mpv()`.

---

## Customization

Configuration lives at the top of `video-player.py`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `REMOTE_STATE_URL` | the vrhsdramaboosters.com URL | Remote state file. Also settable via the `REMOTE_STATE_URL` environment variable in the service file |
| `REMOTE_POLL_INTERVAL_SEC` | 15 | How often to check for new instructions |
| `REMOTE_INITIAL_DELAY_SEC` | 10 | Grace period after boot for network and clock sync |
| `REMOTE_TIMEOUT_SEC` | 15 | Per-request timeout |
| `REMOTE_MEDIA_DIR_URL` | the `/lobby/video/` URL | Directory mirrored into `VIDEO_DIR`. Also settable via the `REMOTE_MEDIA_DIR_URL` environment variable |
| `SYNC_ENABLED` | `True` | Set `False` to turn media sync off entirely |
| `SYNC_INTERVAL_SEC` | 300 | How often to mirror the media directory |
| `SYNC_MIN_FREE_BYTES` | 1 GB | Free space to preserve on the SD card |
| `SYNC_MAX_FILE_BYTES` | 8 GB | Largest file the sync will download |
| `SYNC_DELETE_REMOVED` | `False` | Whether to delete local files removed from the server |
| `DISPLAY_TZ` | `America/Chicago` | Timezone for on-screen times |
| `VIDEO_DIR` | `/home/pi/videos` | SD card video directory |
| `USB_MOUNT_ROOT` | `/media/pi` | Where USB drives mount |
| `STATE_FILE` | `.../video-player/state.json` | Persisted state |
| `DEFAULT_FILES` | `default.mp4`, `default.mov` | Fallback filenames, in priority order |
| `SUPPORTED_EXTENSIONS` | `.mp4 .mov .avi .mkv .webm` | Recognized formats |
| `PIN_EXIT` / `PIN_PREV` / `PIN_NEXT` / `PIN_PLAY` | 17 / 27 / 22 / 23 | GPIO pins (BCM) |
| `RESCAN_INTERVAL_MS` | 5000 | How often to rescan for files |
| `MPV_MAX_FAILURES` | 3 | Fast exits before a file is quarantined |
| `MENU_*` | — | Menu colors, fonts, spacing |

The installed script is at `/usr/local/bin/video-player.py` — edit that, or
re-run `install.sh` after editing the repo copy, then
`sudo systemctl restart video-player`.

## Tests

The precedence logic is covered by tests that stub out pygame and mpv, so they
run anywhere — no display, no GPIO, no Pi required:

```bash
python3 tests/test_logic.py
python3 tests/test_scenarios.py
python3 tests/test_sync.py
```

- `test_logic.py` — filename safety, resolution, timestamp handling, payload
  validation, Apache listing parsing, and the size/timestamp comparison
- `test_scenarios.py` — the 8:00/8:05/8:06/9:00 sequence above, plus reboots,
  missing files, unplayable files, outages, and how downloads affect playback
- `test_sync.py` — the real download path against a local HTTP server: atomic
  renames, timestamp preservation, truncated downloads, and a full disk

## Repository Files

| File | Purpose |
|------|---------|
| `video-player.py` | The player — menu, GPIO, remote polling, mpv control |
| `video-player.service` | Systemd unit |
| `install.sh` | Automated installer |
| `state.json.example` | Sample remote state file |
| `tests/` | Test suites for the precedence and fallback logic |
| `SETUP.md` | Raspberry Pi setup from a blank SD card |
| `QUICKSTART.md` | Condensed installation steps |
| `README.md` | This document |
| `COMPLETE-GUIDE.md` | End-to-end process overview |
| `WEB-ADMIN-SPEC.md` | Integration contract for the website-side upload and selection app |
