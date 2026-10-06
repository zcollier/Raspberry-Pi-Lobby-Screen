# Project Summary — VRHS Lobby Screen

Last updated: 2026-10-06

Digital signage for the VRHS lobby monitors. A Raspberry Pi 4 plays video on an
HDMI display and is controlled three ways: physical buttons in the lobby, a JSON
file on the theatre website (`vrhstheatre.com`), and automatic media downloads
from that website.

---

## Current state at a glance

| Area | Status |
|------|--------|
| Physical GPIO buttons | **Fixed and working on the Pi** (gpiozero backend) |
| Button responsiveness | Fixed in code (no more half-second hold); on-Pi confirmation pending |
| `q` during playback | Fixed: returns to the menu instead of relaunching |
| Resume after restart | Always resumes the last video, even after EXIT/`q` |
| USB sticks | Confirmed working on the Pi |
| One-click deploy | `deploy.sh` + "Deploy Video Player" desktop icon, working on the Pi |
| Website | **Moved to `vrhstheatre.com`**; `/lobby/` live there, checked 2026-09-29 |
| Website URLs | Set in `/home/pi/video-player/config.json` (editable over SMB); **deployed 2026-09-29** |
| Remote video selection (`state.json`) | Built and tested; verified against the new site |
| Automatic media sync (`/lobby/video/`) | Built and tested; verified against the new site |
| USB webcam live source | **Working on the Pi** at 1920x1080 MJPEG; latency fix deployed 2026-10-06 |
| Web upload/admin app | Ported to the `vrhstheatre.com` repo and committed there (`33e9ffd`) |
| Git | Everything deployed is committed (webcam `b99992a`, latency fix 2026-10-06) |

### Progress log

- **2026-10-06** — Webcam tested on real hardware and working. Fixed a bug that
  had silently dropped mpv's input-buffering fix, which made the live picture
  lag noticeably; the user reports it is much better now. Capture raised to
  1920x1080 on the Pi through `config.json`, also working. Details below.
- **2026-10-02** — Commit `b99992a`: USB webcam as a live source in the menu
  and in `state.json` (`"video": "webcam"`). The config.json change from
  2026-09-29 was committed earlier as `bf278ab`.
- **2026-09-29** — The website moved to `vrhstheatre.com`. Website URLs now come
  from `config.json` in the SMB-shared `video-player` folder instead of being
  hard-coded or set in the service file. Deployed to the Pi the same day; the
  user reports it working. Details below. Committed as `bf278ab`.
- **2026-09-25** — GPIO buttons diagnosed and fixed, `q` relaunch bug fixed,
  button hold-time fixed, resume-on-restart added, one-click deploy added.
  Discovered the website's `/lobby/` folder is gone (404). Details below.
  Commits `a0d263a`, `c794e1b`, `ec59e65`.
- **2026-08-20** — No code changes since the last save. Commit `ecea397` landed,
  adding `gpio-check.py`.
- **2026-08-14** — This summary first written. Remote selection and media sync
  complete and tested against the live server. GPIO buttons reported broken.
- **2026-08-12** — Commit `e8512e2`: player restructure, remote selection, media
  sync, three test suites, `lobby-check`, and `WEB-ADMIN-SPEC.md`.

---

## Session 2026-10-06 — webcam on real hardware, latency fix

The webcam (`b99992a`) was deployed and works on the Pi: "[Live] Webcam"
appears in the menu and plays full screen.

**Latency bug, fixed.** The picture lagged well behind real life. mpv's
`low-latency` profile sets `demuxer-lavf-o-add=fflags=+nobuffer`, but
`launch_mpv()` then passed `--demuxer-lavf-o=input_format=…,video_size=…`,
which *replaces* the whole option list and dropped `nobuffer`. Each capture
option now goes in its own `--demuxer-lavf-o-add=`, `fflags=+nobuffer` is added
explicitly, and `--cache=no` is set. `test_logic.py` checks that no plain
`--demuxer-lavf-o=` is ever passed. Deployed; the user reports the lag is much
better. (The profile's contents were from mpv's built-in profile, recalled
rather than checked against the Pi's mpv; the fix works either way.)

**1080p.** The Pi's `config.json` now has `"webcam_size": "1920x1080"`, and the
user reports it works. The repo's `config.json` was updated to match; the code
default (used when the setting is missing) is still `1280x720`.

Remaining latency levers if needed: the TV's Game Mode (TV processing delay),
dropping to `640x480` (the Pi 4 decodes MJPEG in software, so a delay that grows
over time means it can't keep up), and better lighting (dim rooms make webcams
drop their frame rate).

---

## Session 2026-09-29 — website moved, URLs made configurable

The lobby feature now lives on **`https://vrhstheatre.com/lobby/`**. Checked
live: `state.json` returns 200 `application/json` with no-cache headers (so its
`.htaccess` is deployed), `/lobby/video/` is an Apache listing the player parses
(`Peter-Pan-Goes-Wrong_no-sponsors.mp4`, `default.mov`), and file HEADs return
`Content-Length` + `Last-Modified`. Plain Apache, no CDN. `www.` also works.
The player's `--check-remote` passes end to end against it.

**`config.json`** (new, in the repo, read in place at
`/home/pi/video-player/config.json`):

```json
{
  "state_url": "https://vrhstheatre.com/lobby/state.json",
  "media_url": "https://vrhstheatre.com/lobby/video/"
}
```

- Precedence per setting: `config.json` → `REMOTE_STATE_URL` /
  `REMOTE_MEDIA_DIR_URL` env vars → built-in defaults (now `vrhstheatre.com`)
- Read once at startup; a restart (the deploy icon) applies an edit
- Missing file is silent; broken JSON, a non-object, or a non-http(s) URL is
  logged as `Config problem, using fallback: …` and the player keeps running
- `media_url` gets a trailing slash added if missing
- Startup logs `Config from <source>: state=… media=…`
  (`journalctl -u video-player -b | grep Config`)
- Override the file's location with `VIDEO_PLAYER_CONFIG`
- `deploy.sh` refuses to deploy if `config.json` isn't valid JSON

Also: removed the old-domain `Environment=REMOTE_STATE_URL=` line from
`video-player.service` (it would otherwise have been a stale fallback), updated
`lobby-check`, `install.sh`, and all docs to the new domain, and added 15
config tests to `test_logic.py`.

**Media download verified against the new host** (from a Mac, using the
player's own `remote_file_meta()` / `download_media()`): `default.mov`
downloaded at 14,226,197 bytes with the server's mtime, was a valid QuickTime
file, left no `.part` behind, and `needs_download()` then reported "up to date".

**Deployed 2026-09-29** by copying `config.json`, `video-player.py`,
`video-player.service` and `deploy.sh` into the `video-player` share and running
the deploy icon (which installs the changed service file and runs
`daemon-reload`). The user reports it working; specific log lines weren't
checked in-session. To confirm in detail:
`journalctl -u video-player -b | grep Config` should show
`state=https://vrhstheatre.com/lobby/state.json`, and `lobby-check --sync`
lists what downloads.

---

## Session 2026-09-25 — what was found and fixed

### GPIO buttons: root cause confirmed

Not a code regression — `setup_gpio()` was byte-identical to the original. The
Pi runs **Raspberry Pi OS trixie**, where `RPi.GPIO`'s edge detection (which
uses the legacy sysfs GPIO interface) fails. The journal showed it directly:

```
GPIO not available (Failed to add edge detection). Keyboard-only mode.
```

The player silently dropped to keyboard-only mode, so only the buttons broke.

**Fix (`a0d263a`):** `setup_gpio()` now tries **gpiozero** first (lgpio backend,
kernel character-device API) and falls back to `RPi.GPIO`. The log names the
backend in use, or each backend's failure reason. `install.sh` now installs
`python3-gpiozero python3-lgpio`. Confirmed on the Pi:
`GPIO initialized (gpiozero).`, `pinctrl` shows all four pins as pulled-up
inputs, and presses work.

**Follow-up (`ec59e65`):** buttons then needed a ~0.5 s hold. lgpio's debounce
means "level must be stable for N ms", not RPi.GPIO's "ignore repeats for N ms",
so the 300 ms `bounce_time` became a 300 ms required hold. Now:

- `BUTTON_SETTLE_MS = 20` — gpiozero `bounce_time`, filters electrical noise
- `BUTTON_DEBOUNCE_MS = 300` — software lockout per button, restoring the old
  "ignore repeats" behavior

If a single press ever double-fires, raise `BUTTON_SETTLE_MS` to ~50. Whether
this version is deployed on the Pi has not been confirmed.

### `q` relaunched the video immediately (`c794e1b`)

Not systemd — `RestartUSec=1min` was confirmed on the Pi. While a video plays
**mpv has keyboard focus**, so `q` is mpv's own quit key: mpv exits, the Python
player keeps running, and since the restructure any mpv exit was treated as a
crash and relaunched. Because mpv runs with `--loop`, a clean exit (code 0) can
only be a user quit, so `handle_mpv_exit()` now treats it like the EXIT button.
Error exits still go through crash recovery. `q` on the menu quits the app;
systemd restarts it after 60 s (`Restart=always`, which the user wants kept).

### Always resume the last video after a restart (`ec59e65`)

Previously EXIT/`q` persisted "show nothing", so a restart came up on the menu.
The original pre-upgrade player always resumed. Now `Player` also persists
`last_target_name/path/source` (not cleared by a local stop), and
`resume_on_startup()` picks: current target → last target → `default.mp4`.
EXIT/`q` still stop playback while the app runs. Older state files without the
new fields migrate automatically; one stopped under the old code has nothing to
resume and plays the default once.

### One-click deploy (`ec59e65`)

- `deploy.sh` — lives in `/home/pi/video-player/`. Compiles `video-player.py`
  first and refuses to install a broken file, copies it to `/usr/local/bin`,
  installs `video-player.service` + `daemon-reload` only if it changed, restarts,
  and shows status. On success the window closes after 5 s; on failure it stays
  open until Enter.
- `deploy-video-player.desktop` — the "Deploy Video Player" icon; runs
  `bash /home/pi/video-player/deploy.sh` in a terminal.
- File Manager → Preferences → "Don't ask options on launch executable file"
  stops the Execute / Execute-in-terminal prompt.

### Website `/lobby/` folder is missing (resolved 2026-09-29 by the move)

Checked 2026-09-25: the site root returns 200, but `/lobby/`, `/lobby/state.json`
and `/lobby/video/` all return **404** (www and non-www). It was live in August.
Likely cause (unconfirmed): in the website repo the entire `lobby/` folder is
untracked, so any redeploy or sync from git would drop it.

Effect: playback is unaffected — the Pi logs a (backed-off) "Could not reach
remote state file … 404" warning and keeps playing. Remote selection and media
sync are dead until the folder is restored.

---

## How the system works

The Pi never accepts an inbound connection — the school network can't allow it.
Everything is driven by the Pi reaching *out*:

```
                    vrhstheatre.com
                    ├── /lobby/state.json     "play this file"
                    └── /lobby/video/         media files to mirror
                              ▲
                              │ outbound HTTPS only
                              │
   [ Raspberry Pi ] ──────────┘
     ├── every 15s   : fetch state.json, act if it changed
     ├── every 5 min : mirror /lobby/video/ into /home/pi/videos/
     ├── every 5s    : rescan local files (SD card + USB drives)
     └── GPIO buttons: EXIT / PREV / NEXT / PLAY
```

### Control precedence: most recent instruction wins

| Time | Event | Result |
|------|-------|--------|
| 8:00 | Website set to `A.mp4` | Plays A |
| 8:05 | Someone presses NEXT in the lobby → `B.mp4` | Plays B |
| 8:06 | Poll runs; website still says `A.mp4` | **Still plays B** |
| 9:00 | Website changed to `C.mp4` | Plays C |

The 8:06 row is the whole design. The Pi does **not** compare the website's
timestamp against its own clock — it remembers a fingerprint of the last remote
instruction it acted on and reacts only when the file's *values* change.

This was deliberate. Clock comparison would have been fragile twice over: the Pi
4 has no battery-backed RTC and reads the wrong time for seconds after every
boot, and a human editing the JSON will eventually forget to update the
timestamp. Change detection depends on neither.

Consequence: re-asserting the same video after a local override requires
changing `updated`, since identical values are a no-op. Whitespace and key order
don't matter — the fingerprint is computed on parsed values.

### Local controls

| Input | Menu | Playing |
|-------|------|---------|
| EXIT button | — | Stop, return to menu |
| PREV / NEXT buttons | Move selection | Switch to previous/next video |
| PLAY button | Play selected | — |
| Up / Down / Enter keys | Move / play | (go to mpv) |
| `q` key | Quit app (systemd restarts in 60 s, resumes last video) | Return to menu (via mpv exit code 0) |

---

## What was built

### 1. Player restructure

`video-player.py` grew from a single-video looper into a state machine. Playback
logic lives in a `Player` class; all input sources — GPIO, keyboard, remote
poll, media sync — funnel through its methods on the main thread, so `mpv_proc`
and the video list have exactly one writer. GPIO callbacks and background
threads only post pygame events.

### 2. Remote selection

A `RemoteWatcher` daemon thread polls `state.json` every 15 seconds and posts an
event. Schema:

```json
{ "version": 1, "video": "spring-musical-2026.mp4", "updated": "2026-08-12T13:00:00Z" }
```

Validation rejects a wrong schema version, a non-object payload, a missing
`video`, and any filename containing a path separator. A malformed file or a
network failure changes nothing — the screen keeps playing.

State lives in `~/.config/video-player/state.json` (migrated from the old
`last_played.txt`). Persisting the last-seen remote fingerprint is what stops a
reboot from re-applying an old instruction over a newer local override.

### 3. Media sync

A separate `SyncWorker` thread mirrors `/lobby/video/` into `/home/pi/videos/`
every 5 minutes. It enumerates via Apache's autoindex listing, then sends one
`HEAD` per file for exact `Content-Length` and `Last-Modified`. A file downloads
when it's missing locally, or when size **or** mtime differs — compared for
*difference*, not "server is newer", so rollbacks propagate too. After download
the local mtime is set to the server's.

Safety properties, all tested:

- Downloads write to a hidden `.part` file and `rename()` into place
- A file still being uploaded is detected and retried
- Downloads refused if they'd leave under 1 GB free on the SD card
- Nothing is ever deleted (`SYNC_DELETE_REMOVED = False`)
- Any failure leaves local files untouched and never interrupts playback
- If the file currently on screen is replaced, mpv relaunches
- A file quarantined as unplayable gets a fresh chance when new content arrives

Images are first-class: `.jpg .jpeg .png .gif .bmp .webp` display full screen
indefinitely via `--image-display-duration=inf`, and can be named in
`state.json` exactly like a video.

### 4. Robustness

- **Crash-loop guard**: if mpv exits with an error within 5 seconds of
  launching, three times running, the file is quarantined and the player falls
  back to the default
- **Fallback chain**: `default.mp4`, then `default.mov`, then first file
  alphabetically. If the requested file is missing, the default plays and the Pi
  *keeps wanting* the target — plug in a USB stick and it switches automatically
- **Outage logging** backs off to roughly every 30 minutes

### 5. Live webcam (`b99992a`, latency fix 2026-10-06)

The first camera matching `/dev/v4l/by-id/*-video-index0` appears as
"[Live] Webcam" at the end of the menu, and `"video": "webcam"` selects it
remotely. mpv opens it as `av://v4l2:…` with no audio, the `low-latency`
profile, `--untimed`, `--cache=no` and `fflags=+nobuffer`. The capture mode
comes from `webcam_size` / `webcam_format` in `config.json` (default
1280x720 MJPEG; `""` lets the camera choose). Unplugging it falls back to the
default video, and replugging switches back to live with its crash-loop
quarantine cleared. The webcam is never the fallback.

### 6. Diagnostics

| Command | Purpose |
|---------|---------|
| `lobby-check` | Wrapper: service status plus the remote check |
| `lobby-check --sync` | Download new/changed media now |
| `video-player.py --check-remote` | Fetch state.json, parse it, resolve the file, list remote media |
| `video-player.py --sync-now` | One foreground sync pass |
| `gpio-check.py` | Button diagnostic (uses RPi.GPIO, so its edge-detection test fails on trixie by design; polling still tests wiring) |
| `pinctrl get 17,27,22,23` | Read pin levels live, even while the player runs — `hi` idle, `lo` pressed |
| `journalctl -u video-player -b \| grep -i gpio` | Which GPIO backend initialized, or why none did |

---

## Verified facts about the environment

- **Pi OS is Raspberry Pi OS trixie.** `python3-gpiozero 2.0.1` and
  `python3-lgpio 0.2.2` are installed. `RPi.GPIO` edge detection does not work.
- **`RestartUSec=1min`** confirmed on the Pi.
- **SMB shares** on the Pi: `pi` (= `/home/pi`), `video-player`
  (= `/home/pi/video-player`), `videos` (= `/home/pi/videos`). SMB cannot write
  into `~/Desktop`, and nothing outside `/home/pi` is reachable — installing into
  `/usr/local/bin` or `/etc/systemd/system` needs a terminal (or `deploy.sh`).
- **USB sticks** mount under `/media/pi/<label>`; files in the stick's root show
  up in the menu within ~5 s. A stale, root-owned `/media/pi/Samsung128` folder
  (stick no longer present) logs "Permission denied" every 5 s;
  `sudo rmdir /media/pi/Samsung128` clears it.
- **The site is now `vrhstheatre.com`** (2026-09-29): plain Apache, no CDN,
  `state.json` served no-cache; media files still carry `max-age=172800`.
- The old `vrhsdramaboosters.com/lobby/` returned 404 on 2026-09-25. The facts
  below were verified there in August:
  - Plain Apache, no CDN; `mod_autoindex` enabled on `/lobby/` and
    `/lobby/video/`. An index file in `/lobby/video/` would silently kill sync.
  - Everything under `/lobby/` was served with a two-day cache header. The Pi is
    immune (unique query parameter); browsers are not.
  - Apache serves half-written files; the size check and post-download
    re-verification handle it.

---

## Deployment

**Normal update:** copy the new `video-player.py` (and `video-player.service`,
if changed) into the `video-player` SMB share, then double-click **Deploy Video
Player** on the Pi's desktop.

**Manual equivalent:**

```bash
sudo cp /home/pi/video-player/video-player.py /usr/local/bin/video-player.py
sudo chmod +x /usr/local/bin/video-player.py
sudo systemctl restart video-player
```

The 2026-09-29 deploy installed the current working tree, which includes
everything from `ec59e65` (button settle time, resume-on-restart, auto-closing
deploy window) plus the `config.json` change. On 2026-10-06 the webcam build
and its latency fix were deployed (only `video-player.py` was copied), and the
Pi's `config.json` was edited by hand to `"webcam_size": "1920x1080"`.

**Changing the website address:** edit `config.json` in the `video-player`
share, then run the deploy icon (or `sudo systemctl restart video-player`).

---

## Open items

### 1. Webcam follow-ups

- Not yet checked: whether the lag grows over long live sessions at 1080p.

### 2. Web upload/admin app ("Lobby TVs")

Built against `WEB-ADMIN-SPEC.md`. Now in `../vrhstheatre.com` (`admin/lobby.php`,
`admin/lobby-lib.php`, `lobby/video/`), committed there as `33e9ffd` "Restored
old Lobby TV code". The live `state.json` on vrhstheatre.com was written
2026-09-29, consistent with it being in use. The original copy in
`../vrhsdramaboosters.com` is still untracked there, along with
`LOBBY-PORT-GUIDE.md`.

### 3. Confirm on the Pi

- Quick taps register and a single press doesn't double-fire
- A restart after `q`/EXIT resumes the last video

### 4. Housekeeping

- `sudo rmdir /media/pi/Samsung128` on the Pi
- Optional: log unreadable USB drives once rather than every 5 s

---

## Testing

Three suites, no pytest dependency, runnable anywhere — pygame and mpv are
stubbed, so no display, GPIO, or Pi required:

```bash
python3 tests/test_logic.py
python3 tests/test_scenarios.py
python3 tests/test_sync.py
```

- **`test_logic.py`** — filename safety, file resolution, timestamps, payload
  validation, Apache listing parsing, size/mtime comparison
- **`test_scenarios.py`** — the 8:00/8:05/8:06/9:00 sequence, reboots, missing
  files, crash-loop quarantine, outages, downloads; plus Scenario 14 (`q` in mpv
  returns to the menu; error exits still relaunch) and Scenario 15 (restart
  resumes the last video even after EXIT; fresh install plays the default)
- **`test_sync.py`** — the real download path against a local HTTP server

All passing as of 2026-10-06. The GPIO backends are not covered by the suites;
they were checked against fake gpiozero/RPi.GPIO modules during the session.

---

## Key design decisions

| Decision | Why |
|----------|-----|
| Outbound polling, no server on the Pi | The network can't accept inbound traffic |
| Change detection, not clock comparison | Pi has no RTC; humans forget to update timestamps |
| State poll 15s, media sync 5 min, separate threads | A long download must not delay a state check |
| Local override survives reboot | Faithful reading of "most recent instruction wins" |
| A local stop does not survive a restart | The screen should always come back up playing; matches the original player |
| gpiozero first, RPi.GPIO fallback | RPi.GPIO edge detection is broken on current Pi OS |
| Short hardware settle + software lockout | lgpio debounce means "hold for N ms", which made buttons feel sluggish |
| mpv exit code 0 = user quit | With `--loop`, playback never ends cleanly on its own |
| `Restart=always`, `RestartSec=60` | Always recover, but give a person time after quitting |
| Deploy script compiles before installing | A half-copied file over SMB must not replace a working player |
| Nothing is ever deleted by default | Deleting files on a machine you can't see should be deliberate |
| Atomic writes everywhere | A power cut must not leave corruption |
| Webcam options appended with `-add` | A plain `--demuxer-lavf-o=` replaces the profile's `fflags=+nobuffer` and brings the lag back |
| Static `state.json`, not PHP-generated | A PHP warning in the response body would break the parse |

---

## File map

| File | Purpose |
|------|---------|
| `video-player.py` | The player — menu, GPIO, remote polling, media sync, mpv control |
| `video-player.service` | Systemd unit (`Restart=always`, `RestartSec=60`) |
| `config.json` | Website URLs (`state_url`, `media_url`), read in place on the Pi |
| `install.sh` | Installer; safe to re-run, restarts a running service |
| `deploy.sh` | One-click deploy, run from the desktop icon |
| `deploy-video-player.desktop` | "Deploy Video Player" desktop launcher |
| `lobby-check` | Diagnostic wrapper installed to `/usr/local/bin` |
| `gpio-check.py` | Button diagnostic — polling vs edge detection |
| `state.json.example` | Sample remote state file |
| `tests/` | Three test suites plus a shared harness |
| `README.md` | Full documentation |
| `QUICKSTART.md` | Condensed install |
| `SETUP.md` | Pi setup from a blank SD card |
| `COMPLETE-GUIDE.md` | End-to-end overview |
| `WEB-ADMIN-SPEC.md` | Integration contract for the website-side app |
| `project-summary.md` | This document |

Configuration lives in a block at the top of `video-player.py`. The
authoritative validation rules are `parse_remote_payload()` and
`is_safe_filename()`; sync behavior is `sync_once()`; startup behavior is
`Player.resume_on_startup()`.
