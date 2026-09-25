# Project Summary — VRHS Lobby Screen

Last updated: 2026-08-20

Digital signage for the VRHS lobby monitors. A Raspberry Pi 4 plays video on an
HDMI display and is controlled three ways: physical buttons in the lobby, a JSON
file on the Boosters website, and automatic media downloads from that website.

---

## Current state at a glance

| Area | Status |
|------|--------|
| Remote video selection (`state.json`) | Built, tested, live on the website |
| Automatic media sync (`/lobby/video/`) | Built, tested against the live server |
| Physical GPIO buttons | **Reported not working — diagnosis in progress** |
| Web upload/admin app | Not started; spec written for another agent |
| Git | Three commits, latest `ecea397`; only this file is untracked |

### Progress log

- **2026-08-20** — No code changes since the last save. Commit `ecea397` landed,
  adding `gpio-check.py`. The GPIO fault remains unresolved: the diagnostic has
  not been run on hardware, and no fix exists in `video-player.py`.
- **2026-08-14** — This summary first written. Remote selection and media sync
  complete and tested against the live server. GPIO buttons reported broken;
  ruled out the upgrades as the cause and wrote `gpio-check.py`.
- **2026-08-12** — Commit `e8512e2`: player restructure, remote selection, media
  sync, three test suites, `lobby-check`, and `WEB-ADMIN-SPEC.md`.

---

## How the system works

The Pi never accepts an inbound connection — the school network can't allow it.
Everything is driven by the Pi reaching *out*:

```
                    vrhsdramaboosters.com
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

---

## What was built

### 1. Player restructure

`video-player.py` grew from a single-video looper into a state machine. Playback
logic moved into a `Player` class, collapsing six duplicated inline handlers into
`start_playback()` / `stop_playback()` / `step_selection()`. All four input
sources — GPIO, keyboard, remote poll, media sync — funnel through those methods
on the main thread, so `mpv_proc` and the video list have exactly one writer.

The integration seam was already there: GPIO callbacks post pygame events rather
than touching state. Background threads do the same.

Fixed along the way: keyboard `Q` was missing the `time.sleep(0.5)` that the EXIT
button had before restoring the display.

### 2. Remote selection

A `RemoteWatcher` daemon thread polls `state.json` every 15 seconds and posts an
event. Schema:

```json
{ "version": 1, "video": "spring-musical-2026.mp4", "updated": "2026-08-12T13:00:00Z" }
```

Validation rejects a wrong schema version, a non-object payload, a missing
`video`, and any filename containing a path separator. A malformed file or a
network failure changes nothing — the screen keeps playing.

State moved from `last_played.txt` to `state.json` under
`~/.config/video-player/`, with automatic migration. Persisting the last-seen
remote fingerprint is what stops a reboot from re-applying an old instruction
over a newer local override.

### 3. Media sync

A separate `SyncWorker` thread mirrors `/lobby/video/` into `/home/pi/videos/`
every 5 minutes. It enumerates via Apache's autoindex listing, then sends one
`HEAD` per file for exact `Content-Length` and `Last-Modified`. A file downloads
when it's missing locally, or when size **or** mtime differs — compared for
*difference*, not "server is newer", so rollbacks propagate too.

After download the local mtime is set to the server's, which is what makes the
comparison stable across passes.

Safety properties, all tested:

- Downloads write to a hidden `.part` file and `rename()` into place — a power
  cut can't leave a truncated video where the player would try to play it
- A file still being uploaded is detected and retried (see below)
- Downloads refused if they'd leave under 1 GB free on the SD card
- Nothing is ever deleted (`SYNC_DELETE_REMOVED = False`)
- Any failure leaves local files untouched and never interrupts playback
- If the file currently on screen is replaced, mpv relaunches
- A file quarantined as unplayable gets a fresh chance when new content arrives

Images are first-class: `.jpg .jpeg .png .gif .bmp .webp` display full screen
indefinitely via `--image-display-duration=inf`, and can be named in
`state.json` exactly like a video.

### 4. Robustness

- **Crash-loop guard**: if mpv exits within 5 seconds of launching, three times
  running, the file is quarantined and the player falls back to the default
- **Fallback chain**: `default.mp4`, then `default.mov`, then first file
  alphabetically. If the requested file is missing, the default plays and the Pi
  *keeps wanting* the target — plug in a USB stick and it switches automatically
- **Outage logging** backs off to roughly every 30 minutes, derived from the poll
  interval so it self-adjusts

### 5. Diagnostics

| Command | Purpose |
|---------|---------|
| `lobby-check` | Wrapper: service status plus the remote check |
| `lobby-check --sync` | Download new/changed media now |
| `video-player.py --check-remote` | Fetch state.json, parse it, resolve the file, list every remote media file with size/timestamp/would-download |
| `video-player.py --sync-now` | One foreground sync pass |
| `gpio-check.py` | Button diagnostic (see open items) |

---

## Verified facts about the environment

Established by probing the live site, not assumed:

- **Plain Apache, no CDN.** This is why the cache-busting works.
- **`mod_autoindex` is enabled** on `/lobby/` and `/lobby/video/`. The media sync
  depends on this. An `index.html`/`index.php` placed in `/lobby/video/` would
  silently kill it.
- **`state.json` is live and valid**, served as `application/json`.
- **Everything under `/lobby/` is served with `cache-control: max-age=172800`
  — two days.** The Pi is immune (unique query parameter per request, no
  intermediate cache), but a *browser* will show stale content for two days.
  Verify edits with `lobby-check`, never a browser. An `.htaccess` snippet to fix
  this at the source is in `README.md`.
- **Apache serves half-written files.** Observed directly: `test.mp4` was fetched
  mid-upload, HEAD reported 4,915,200 bytes and the body delivered 4,980,736. The
  size check refused the partial file and the retry succeeded. A post-download
  re-verification was added as a result. Recommended workflow: upload under a
  temporary name and rename when complete.

---

## Deployment status

**Confirmed on the Pi:** the player is installed and working. Videos play,
remote selection was deployed and functioning.

**Not confirmed:**

- Whether the media-sync version of `video-player.py` has been copied over yet
- Whether `RestartSec=60` was applied (check with
  `systemctl show video-player -p RestartUSec`; expect `1min`)
- Whether `lobby-check` is installed (it is in the repo and installed by
  `install.sh`)

Deployment is a file copy over the open SMB share plus:

```bash
sudo cp /home/pi/video-player/video-player.py /usr/local/bin/video-player.py
sudo chmod +x /usr/local/bin/video-player.py
sudo systemctl restart video-player
```

`daemon-reload` is only needed when `video-player.service` itself changes. No new
dependencies were introduced — everything uses the Python standard library.

---

## Open items

### 1. GPIO buttons reported not working (active, unresolved)

Verified against the original commit `92aacc3`: `setup_gpio()` and
`cleanup_gpio()` are **identical to the original**, and all four button handlers
are still wired in the main loop. The upgrades did not touch the GPIO input path,
which points at the environment or the hardware.

**No code fix has landed yet.** Commit `ecea397` is titled "Maybe fixed GPIO
buttons" but contains only `gpio-check.py` — the diagnostic script, not a fix.
`video-player.py` has not been modified since `e8512e2`; it still uses
`RPi.GPIO` with `add_event_detect()`, which is precisely the call that fails on
newer Raspberry Pi OS kernels. If that turns out to be the cause, the fix is
still to be written.

**Nothing has been reported back from running the diagnostic on hardware**, so
the root cause is still unknown — the two candidate explanations below are both
still open.

Diagnosis starts with:

```bash
sudo journalctl -u video-player -b | grep -i gpio
```

- `GPIO not available (...)` → the player fell back to keyboard-only at startup.
  The parenthesised reason matters. `Failed to add edge detection` is the likely
  one after an `apt upgrade` — `RPi.GPIO` edge detection breaks on newer
  Raspberry Pi OS kernels. Fix would be migrating to `gpiozero` on the `lgpio`
  backend (`python3-gpiozero`, available via apt, no third-party dependency),
  ideally with an `RPi.GPIO` fallback.
- `GPIO initialized.` → pins claimed fine; run `gpio-check.py` (stop the service
  first). It polls the pins *and* separately tries to register edge detection,
  which separates a wiring fault from the kernel issue. All four failing at once
  points at the shared ground wire.

Two answers would narrow this quickly: whether `apt upgrade` was run recently,
and whether all four buttons failed together or only some.

### 2. Web upload/admin app

Being built by a separate agent against `WEB-ADMIN-SPEC.md`. Dreamhost LAMP, no
third-party dependencies. The spec is self-contained — it doesn't require reading
the Python.

The four failure modes most likely to bite that build, all called out in the
spec:

1. An index file in `/lobby/video/` kills the directory listing and silently
   stops media sync forever
2. `"version": "1"` as a string causes the entire file to be discarded
3. Volatile fields in `state.json` (e.g. a regenerated timestamp on every page
   load) make the Pi re-apply constantly and break the physical buttons
4. Writing `state.json` on page load rather than on submit does the same

### 3. Housekeeping

- `project-summary.md` is untracked
- Optional: `.htaccess` in `/lobby/` to stop the 2-day cache header on `.json`

---

## Testing

Three suites, no pytest dependency, runnable anywhere — pygame and mpv are
stubbed, so no display, GPIO, or Pi required:

```bash
python3 tests/test_logic.py
python3 tests/test_scenarios.py
python3 tests/test_sync.py
```

- **`test_logic.py`** — filename safety and path-traversal rejection, file
  resolution, timestamp parsing and CDT/CST display, payload validation, Apache
  listing parsing (fixture captured from the live host), size/mtime comparison
- **`test_scenarios.py`** — the 8:00/8:05/8:06/9:00 sequence, reboots preserving
  a local override, missing files, crash-loop quarantine, outages, and how
  completed downloads affect playback
- **`test_sync.py`** — the real download path against a local HTTP server:
  atomic renames, mtime preservation, truncated downloads, a full disk, an
  unreachable server

All passing as of the last run.

---

## Key design decisions

| Decision | Why |
|----------|-----|
| Outbound polling, no server on the Pi | The network can't accept inbound traffic |
| Change detection, not clock comparison | Pi has no RTC; humans forget to update timestamps |
| State poll 15s, media sync 5 min, separate threads | A multi-minute video download must not delay a state check; per-file HEAD requests every 15s would be tens of thousands of requests a day |
| Local override survives reboot | Faithful reading of "most recent instruction wins" |
| Nothing is ever deleted by default | Deleting files on a machine you can't see should be deliberate |
| Images are playable, not just stored | A poster or announcement slide should work like a video |
| Atomic writes everywhere | The player may read at any moment; a power cut must not leave corruption |
| Static `state.json`, not PHP-generated | A PHP warning in the response body would break the parse |

---

## File map

| File | Purpose |
|------|---------|
| `video-player.py` | The player — menu, GPIO, remote polling, media sync, mpv control |
| `video-player.service` | Systemd unit (`RestartSec=60`, `REMOTE_STATE_URL`) |
| `install.sh` | Installer; safe to re-run, restarts a running service |
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
`is_safe_filename()`; sync behavior is `sync_once()`.
