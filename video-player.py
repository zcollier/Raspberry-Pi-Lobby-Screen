#!/usr/bin/env python3
"""
VRHS Lobby Screen — Interactive Video Player

- Fullscreen pygame menu with GPIO button support
- Remote control by polling a JSON file over HTTPS (outbound only — no inbound
  ports, no server running on the Pi)
- "Most recent instruction wins" between remote and local control, resolved by
  change detection rather than clock comparison (see RemoteWatcher below)
- State persistence: survives reboots and loss of internet access

GPIO buttons (BCM numbering, wire each between pin and GND):
  Pin 17 = EXIT  — stop video, return to menu
  Pin 27 = PREV  — previous item in menu
  Pin 22 = NEXT  — next item in menu
  Pin 23 = PLAY  — play selected video

Keyboard fallback (for testing without GPIO):
  Up/Down arrows = navigate menu
  Enter          = play selected video
  Q              = return to menu (while playing) or quit app (on menu)

Media files published to the remote video directory are mirrored into the local
video directory automatically, so new videos and images reach the Pi without
anyone touching it.

Command line:
  video-player.py                 Run the player
  video-player.py --check-remote  Report on the remote state file and the media
                                  directory, then exit. Use this to verify
                                  hosting and caching without touching the
                                  display.
  video-player.py --sync-now      Download new or changed media files now, then
                                  exit. Useful for the first bulk download.
"""

import os
import sys
import json
import time
import shutil
import hashlib
import logging
import argparse
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from enum import Enum, auto
from html.parser import HTMLParser
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pygame

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VIDEO_DIR = "/home/pi/videos"
USB_MOUNT_ROOT = "/media/pi"
STATE_FILE = "/home/pi/.config/video-player/state.json"
LEGACY_STATE_FILE = "/home/pi/.config/video-player/last_played.txt"
DEFAULT_FILES = ["default.mp4", "default.mov"]

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
SUPPORTED_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS

# Remote state. Override the URL with the REMOTE_STATE_URL environment variable
# (set it in video-player.service) if the file ever moves.
REMOTE_STATE_URL = os.environ.get(
    "REMOTE_STATE_URL",
    "https://www.vrhsdramaboosters.com/lobby/state.json",
)
REMOTE_POLL_INTERVAL_SEC = 15      # How often to check the remote state file
REMOTE_INITIAL_DELAY_SEC = 10      # Grace period after boot for network + NTP
REMOTE_TIMEOUT_SEC = 15            # Per-request timeout
REMOTE_MAX_BYTES = 64 * 1024       # Refuse to read more than this
REMOTE_SCHEMA_VERSION = 1          # Payload versions this build understands

# During an outage, log roughly every half hour rather than on every failed
# poll, so an overnight internet failure doesn't fill the journal. Derived from
# the poll interval so it stays sane if the interval changes.
REMOTE_FAILURE_LOG_EVERY = max(1, round(1800 / REMOTE_POLL_INTERVAL_SEC))

# ---------------------------------------------------------------------------
# File sync
#
# Media files published to REMOTE_MEDIA_DIR_URL are mirrored into VIDEO_DIR. A
# file is downloaded when it is missing locally, or when its size or
# modification time differs from the copy on the server.
#
# This runs on its own slower schedule rather than alongside every state.json
# poll: each pass costs one directory listing plus one HEAD request per file,
# and at the 15-second state poll that would be tens of thousands of requests a
# day against the web host. Set SYNC_INTERVAL_SEC = REMOTE_POLL_INTERVAL_SEC if
# you want them in lockstep anyway.
# ---------------------------------------------------------------------------

REMOTE_MEDIA_DIR_URL = os.environ.get(
    "REMOTE_MEDIA_DIR_URL",
    "https://www.vrhsdramaboosters.com/lobby/video/",
)
SYNC_ENABLED = True
SYNC_INTERVAL_SEC = 300            # How often to mirror the remote directory
SYNC_INITIAL_DELAY_SEC = 20        # Let the first state poll happen first
SYNC_TIMEOUT_SEC = 600             # Per-file download timeout (videos are big)
SYNC_CHUNK_BYTES = 256 * 1024
SYNC_MAX_FILE_BYTES = 8 * 1024 ** 3        # Refuse absurdly large downloads
SYNC_MIN_FREE_BYTES = 1024 ** 3            # Keep at least this much SD free
SYNC_MTIME_TOLERANCE_SEC = 2               # Filesystem timestamp granularity

# Files removed from the server are left alone by default. Deleting is the kind
# of thing you want to opt into deliberately on a machine you can't see.
SYNC_DELETE_REMOVED = False

# Timestamps are stored in UTC and displayed in this zone. Use the IANA zone,
# not "CDT" — the zone resolves to CDT or CST automatically by date.
DISPLAY_TZ = ZoneInfo("America/Chicago")

# GPIO BCM pin numbers
PIN_EXIT = 17
PIN_PREV = 27
PIN_NEXT = 22
PIN_PLAY = 23

BUTTON_DEBOUNCE_MS = 300

# Menu appearance
MENU_BG_COLOR        = (10, 10, 10)
MENU_TEXT_COLOR      = (220, 220, 220)
MENU_HIGHLIGHT_BG    = (50, 100, 180)
MENU_HIGHLIGHT_TEXT  = (255, 255, 255)
MENU_STATUS_COLOR    = (120, 120, 120)
MENU_WARN_COLOR      = (200, 150, 80)
MENU_ERROR_COLOR     = (200, 80, 80)
MENU_FONT_SIZE       = 36
MENU_TITLE_FONT_SIZE = 48
MENU_STATUS_FONT_SIZE = 26
MENU_ITEM_HEIGHT     = 50
MENU_PADDING         = 40

# How often (ms) to check if mpv has exited on its own
MPV_POLL_INTERVAL_MS = 250

# How often (ms) to re-scan for new/removed video files
RESCAN_INTERVAL_MS = 5000

# Crash-loop protection: if mpv exits within this many seconds of launching, the
# launch is treated as a failure. After MPV_MAX_FAILURES consecutive failures
# the file is quarantined and the player falls back to the default video.
MPV_MIN_HEALTHY_SEC = 5.0
MPV_MAX_FAILURES = 3

# ---------------------------------------------------------------------------
# Custom pygame event types (posted from GPIO callbacks and the poller thread)
# ---------------------------------------------------------------------------

EVT_BTN_EXIT   = pygame.USEREVENT + 1
EVT_BTN_PREV   = pygame.USEREVENT + 2
EVT_BTN_NEXT   = pygame.USEREVENT + 3
EVT_BTN_PLAY   = pygame.USEREVENT + 4
EVT_RESCAN     = pygame.USEREVENT + 5
EVT_REMOTE     = pygame.USEREVENT + 6
EVT_SYNC       = pygame.USEREVENT + 7

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class AppState(Enum):
    MENU    = auto()
    PLAYING = auto()


class Source(str, Enum):
    """Where the current instruction came from."""
    REMOTE   = "remote"
    LOCAL    = "local"
    FALLBACK = "fallback"
    NONE     = "none"

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value) -> datetime | None:
    """
    Parse an ISO 8601 timestamp. Accepts a trailing 'Z'. A timestamp with no
    zone is assumed to be local (America/Chicago), since that is what a human
    hand-editing the file is most likely to mean.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=DISPLAY_TZ)
    return parsed


def format_local(dt: datetime | None) -> str:
    """Render a timestamp in the display timezone, e.g. '8:05 AM CDT'."""
    if dt is None:
        return "—"
    local = dt.astimezone(DISPLAY_TZ)
    stamp = local.strftime("%I:%M %p %Z")
    return stamp[1:] if stamp.startswith("0") else stamp

# ---------------------------------------------------------------------------
# Remote state
# ---------------------------------------------------------------------------


class RemoteInstruction:
    """One parsed, validated instruction from the remote state file."""

    __slots__ = ("fingerprint", "video", "updated", "updated_raw", "fetched_at")

    def __init__(self, fingerprint, video, updated, updated_raw, fetched_at):
        self.fingerprint = fingerprint
        self.video       = video
        self.updated     = updated
        self.updated_raw = updated_raw
        self.fetched_at  = fetched_at


def fingerprint_payload(data: dict) -> str:
    """
    Identity of an instruction. Any edit to the file — including bumping only
    the timestamp — produces a new fingerprint and therefore counts as a new
    instruction. That is what makes re-asserting the same video possible after
    someone has overridden it locally.
    """
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def parse_remote_payload(raw: bytes, fetched_at: datetime) -> RemoteInstruction:
    """
    Validate a remote payload. Raises ValueError with a human-readable reason if
    the payload is unusable — callers log it and keep playing whatever is on.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"not valid UTF-8: {exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")

    version = data.get("version", REMOTE_SCHEMA_VERSION)
    if version != REMOTE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema version {version!r} "
            f"(this player understands version {REMOTE_SCHEMA_VERSION})"
        )

    video = data.get("video")
    if not isinstance(video, str) or not video.strip():
        raise ValueError("missing or empty 'video' field")
    video = video.strip()

    if not is_safe_filename(video):
        raise ValueError(
            f"'video' must be a bare filename with no path separators, got {video!r}"
        )

    updated_raw = data.get("updated")
    return RemoteInstruction(
        fingerprint=fingerprint_payload(data),
        video=video,
        updated=parse_iso(updated_raw),
        updated_raw=updated_raw if isinstance(updated_raw, str) else None,
        fetched_at=fetched_at,
    )


def http_open(url: str, method: str = "GET", extra_headers: dict | None = None,
              timeout: int = REMOTE_TIMEOUT_SEC):
    """
    Open a URL with cache-defeating headers and a cache-busting query parameter.

    Everything this player fetches is something a stale copy would silently
    break, so no request is ever allowed to be served from a cache.
    """
    separator = "&" if "?" in url else "?"
    busted = f"{url}{separator}_={int(time.time())}"

    headers = {
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
        "User-Agent": "vrhs-lobby-player/2.0",
    }
    if extra_headers:
        headers.update(extra_headers)

    request = urllib.request.Request(busted, headers=headers, method=method)
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_remote_state(etag: str | None) -> tuple[bytes | None, str | None, dict]:
    """
    Fetch the remote state file.

    Returns (raw_bytes, etag, info). raw_bytes is None when the server answers
    304 Not Modified. Raises on network/HTTP errors.
    """
    extra = {"Accept": "application/json, text/plain, */*"}
    if etag:
        extra["If-None-Match"] = etag

    try:
        with http_open(REMOTE_STATE_URL, extra_headers=extra) as response:
            info = {
                "status": response.status,
                "content_type": response.headers.get("Content-Type"),
                "cache_control": response.headers.get("Cache-Control"),
                "age": response.headers.get("Age"),
                "url": response.url,
            }
            return response.read(REMOTE_MAX_BYTES), response.headers.get("ETag"), info
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return None, etag, {"status": 304}
        raise


class RemoteWatcher:
    """
    Polls the remote state file on a background thread and posts an EVT_REMOTE
    pygame event when something is worth reacting to.

    The thread never touches player state directly — exactly like the GPIO
    callbacks, it only posts events, so every mutation stays on the main loop.
    """

    def __init__(self, poll_interval=REMOTE_POLL_INTERVAL_SEC,
                 initial_delay=REMOTE_INITIAL_DELAY_SEC):
        self.poll_interval = poll_interval
        self.initial_delay = initial_delay
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run, name="remote-watcher", daemon=True
        )
        self._thread.start()
        logger.info(
            f"Remote polling every {self.poll_interval}s: {REMOTE_STATE_URL}"
        )

    def stop(self):
        self._stop.set()

    def _post(self, **payload):
        try:
            pygame.event.post(pygame.event.Event(EVT_REMOTE, payload))
        except pygame.error as exc:
            logger.warning(f"Could not post remote event: {exc}")

    def _run(self):
        if self._stop.wait(self.initial_delay):
            return

        etag = None
        failures = 0

        while True:
            try:
                raw, etag, _info = fetch_remote_state(etag)
                if raw is None:
                    # 304 Not Modified — identical to "nothing new".
                    self._post(instruction=None, error=None)
                else:
                    instruction = parse_remote_payload(raw, utcnow())
                    self._post(instruction=instruction, error=None)
                if failures:
                    logger.info("Remote state file reachable again.")
                failures = 0

            except ValueError as exc:
                # Malformed payload. Log every time: the file is broken and
                # somebody needs to fix it.
                logger.warning(f"Remote state file is invalid — ignoring: {exc}")
                self._post(instruction=None, error=str(exc))

            except Exception as exc:
                # Network failure. Log the first one and then back off to avoid
                # filling the journal while the internet is out overnight.
                failures += 1
                if failures == 1 or failures % REMOTE_FAILURE_LOG_EVERY == 0:
                    logger.warning(
                        f"Could not reach remote state file "
                        f"(attempt {failures}): {exc}"
                    )
                self._post(instruction=None, error=str(exc))

            if self._stop.wait(self.poll_interval):
                return

# ---------------------------------------------------------------------------
# Media file sync
# ---------------------------------------------------------------------------


class ApacheIndexParser(HTMLParser):
    """
    Pull filenames out of an Apache mod_autoindex directory listing.

    HTTP has no directory listing of its own, so this depends on autoindex
    being enabled for the media directory. If the server ever starts returning
    a real page there instead, the listing simply parses to nothing and the
    sync becomes a no-op rather than doing something destructive.
    """

    def __init__(self):
        super().__init__()
        self.names = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        # Skip the column-sort links (?C=N;O=D), the parent directory link
        # (an absolute path), subdirectories, and any absolute URL.
        if href.startswith(("?", "/", "#")) or href.endswith("/") or "://" in href:
            return
        self.names.append(urllib.parse.unquote(href))


def parse_apache_index(html: str) -> list[str]:
    parser = ApacheIndexParser()
    parser.feed(html)
    return parser.names


def is_image(path: str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS


def list_remote_media() -> list[str]:
    """Media filenames published in the remote directory."""
    with http_open(REMOTE_MEDIA_DIR_URL) as response:
        html = response.read(REMOTE_MAX_BYTES * 16).decode("utf-8", errors="replace")

    names = []
    for name in parse_apache_index(html):
        if not is_safe_filename(name):
            logger.warning(f"Skipping unusable remote filename: {name!r}")
            continue
        if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        names.append(name)
    return sorted(set(names))


def remote_file_meta(name: str) -> tuple[int | None, datetime | None]:
    """Size and last-modified time of a remote file, via a HEAD request."""
    url = REMOTE_MEDIA_DIR_URL + urllib.parse.quote(name)
    with http_open(url, method="HEAD") as response:
        raw_size = response.headers.get("Content-Length")
        raw_mtime = response.headers.get("Last-Modified")

    size = None
    if raw_size is not None:
        try:
            size = int(raw_size)
        except ValueError:
            pass

    mtime = None
    if raw_mtime:
        try:
            mtime = parsedate_to_datetime(raw_mtime)
            if mtime.tzinfo is None:
                mtime = mtime.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass

    return size, mtime


def needs_download(local: Path, remote_size, remote_mtime) -> tuple[bool, str]:
    """
    Decide whether the local copy is stale.

    Compares for *difference*, not for "remote is newer", so restoring an older
    file on the server also propagates to the Pi.
    """
    if not local.exists():
        return True, "not present locally"
    try:
        stat = local.stat()
    except OSError as exc:
        return True, f"local copy unreadable ({exc})"

    if remote_size is not None and stat.st_size != remote_size:
        return True, f"size {stat.st_size} -> {remote_size}"

    if remote_mtime is not None:
        local_mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        if abs((remote_mtime - local_mtime).total_seconds()) > SYNC_MTIME_TOLERANCE_SEC:
            return True, (f"modified {format_local(local_mtime)}"
                          f" -> {format_local(remote_mtime)}")

    return False, "up to date"


def download_media(name: str, dest_dir: str, remote_size, remote_mtime) -> int:
    """
    Download one file into dest_dir. Returns the number of bytes written.

    Writes to a hidden .part file and renames it into place, so a power cut
    mid-download can never leave a truncated video where the player would try
    to play it. The dot prefix and the .part suffix both keep the temporary
    file out of the menu while it is being written.
    """
    if remote_size is not None and remote_size > SYNC_MAX_FILE_BYTES:
        raise ValueError(f"refusing {remote_size} byte file (over the size limit)")

    dest_root = Path(dest_dir)
    free = shutil.disk_usage(dest_root).free
    if remote_size is not None and free - remote_size < SYNC_MIN_FREE_BYTES:
        raise ValueError(
            f"not enough free space: {free // 1024**2} MB free, "
            f"need {remote_size // 1024**2} MB plus a "
            f"{SYNC_MIN_FREE_BYTES // 1024**2} MB reserve"
        )

    url = REMOTE_MEDIA_DIR_URL + urllib.parse.quote(name)
    final = dest_root / name
    part = dest_root / f".{name}.part"
    part.unlink(missing_ok=True)

    written = 0
    try:
        with http_open(url, timeout=SYNC_TIMEOUT_SEC) as response, open(part, "wb") as fh:
            while True:
                chunk = response.read(SYNC_CHUNK_BYTES)
                if not chunk:
                    break
                fh.write(chunk)
                written += len(chunk)
                if written > SYNC_MAX_FILE_BYTES:
                    raise ValueError("download exceeded the size limit")

        if remote_size is not None and written != remote_size:
            raise ValueError(f"incomplete download: got {written} of {remote_size} bytes")

        # Guard against downloading a file that is still being uploaded. Apache
        # happily serves a half-written file, and its Content-Length reflects
        # whatever was on disk when the response started. Re-checking afterwards
        # catches a file that kept growing, so a truncated video never reaches
        # the screen — the next sync pass picks up the finished copy.
        settled_size, settled_mtime = remote_file_meta(name)
        if settled_size is not None and settled_size != written:
            raise ValueError(
                f"file changed while downloading ({written} -> {settled_size} bytes); "
                f"it is probably still uploading"
            )
        if (remote_mtime is not None and settled_mtime is not None
                and abs((settled_mtime - remote_mtime).total_seconds())
                > SYNC_MTIME_TOLERANCE_SEC):
            raise ValueError("file was modified while downloading")

        if remote_mtime is not None:
            stamp = remote_mtime.timestamp()
            os.utime(part, (stamp, stamp))

        part.replace(final)      # atomic within the same filesystem
    except BaseException:
        part.unlink(missing_ok=True)
        raise

    return written


def sync_once(dest_dir: str = VIDEO_DIR) -> dict:
    """
    Mirror the remote media directory into dest_dir.

    Never raises: a failure to reach the server, or to fetch one file, leaves
    every local file untouched and is reported in the result.
    """
    result = {"downloaded": [], "errors": [], "removed": [], "checked": 0}

    dest_root = Path(dest_dir)
    if not dest_root.is_dir():
        result["errors"].append(f"local directory missing: {dest_dir}")
        return result

    try:
        remote_names = list_remote_media()
    except Exception as exc:
        result["errors"].append(f"could not list {REMOTE_MEDIA_DIR_URL}: {exc}")
        return result

    result["checked"] = len(remote_names)

    for name in remote_names:
        try:
            size, mtime = remote_file_meta(name)
            stale, reason = needs_download(dest_root / name, size, mtime)
            if not stale:
                continue
            logger.info(f"Downloading {name} ({reason})")
            written = download_media(name, dest_dir, size, mtime)
            logger.info(f"Downloaded {name} ({written // 1024} KB)")
            result["downloaded"].append(name)
        except Exception as exc:
            logger.warning(f"Could not sync {name}: {exc}")
            result["errors"].append(f"{name}: {exc}")

    if SYNC_DELETE_REMOVED:
        keep = set(remote_names)
        for path in dest_root.iterdir():
            if (path.is_file() and not path.name.startswith(".")
                    and path.suffix.lower() in SUPPORTED_EXTENSIONS
                    and path.name not in keep):
                try:
                    path.unlink()
                    result["removed"].append(path.name)
                    logger.info(f"Removed {path.name} (no longer on the server)")
                except OSError as exc:
                    result["errors"].append(f"{path.name}: {exc}")

    return result


class SyncWorker:
    """
    Mirrors the remote media directory on a background thread.

    Deliberately separate from RemoteWatcher: downloading a 200 MB video takes
    minutes, and that must not delay the 15-second state.json checks.
    """

    def __init__(self, interval=SYNC_INTERVAL_SEC, initial_delay=SYNC_INITIAL_DELAY_SEC):
        self.interval = interval
        self.initial_delay = initial_delay
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(
            target=self._run, name="media-sync", daemon=True
        )
        self._thread.start()
        logger.info(
            f"Media sync every {self.interval}s: {REMOTE_MEDIA_DIR_URL}"
        )

    def stop(self):
        self._stop.set()

    def _run(self):
        if self._stop.wait(self.initial_delay):
            return
        while True:
            result = sync_once()
            try:
                pygame.event.post(pygame.event.Event(EVT_SYNC, result))
            except pygame.error as exc:
                logger.warning(f"Could not post sync event: {exc}")
            if self._stop.wait(self.interval):
                return

# ---------------------------------------------------------------------------
# GPIO
# ---------------------------------------------------------------------------

GPIO_AVAILABLE = False


def setup_gpio():
    global GPIO_AVAILABLE
    try:
        import RPi.GPIO as GPIO

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        pin_to_event = {
            PIN_EXIT: EVT_BTN_EXIT,
            PIN_PREV: EVT_BTN_PREV,
            PIN_NEXT: EVT_BTN_NEXT,
            PIN_PLAY: EVT_BTN_PLAY,
        }

        def make_callback(evt_type):
            def callback(channel):
                pygame.event.post(pygame.event.Event(evt_type))
            return callback

        for pin, evt in pin_to_event.items():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(
                pin, GPIO.FALLING,
                callback=make_callback(evt),
                bouncetime=BUTTON_DEBOUNCE_MS,
            )

        GPIO_AVAILABLE = True
        logger.info("GPIO initialized.")
    except (ImportError, RuntimeError) as exc:
        logger.warning(f"GPIO not available ({exc}). Keyboard-only mode.")


def cleanup_gpio():
    if GPIO_AVAILABLE:
        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Video discovery
# ---------------------------------------------------------------------------


def is_safe_filename(name: str) -> bool:
    """
    True if `name` is a bare filename safe to look up locally.

    The remote file is input from a host we do not fully control, so a value
    like '../../etc/shadow' must never be resolved. Rejecting anything that is
    not a plain filename costs nothing and closes that door.
    """
    if not isinstance(name, str) or not name.strip():
        return False
    if name != name.strip():
        return False
    if "/" in name or "\\" in name or "\x00" in name:
        return False
    if name in (".", ".."):
        return False
    if Path(name).name != name:
        return False
    return True


def discover_videos() -> list[str]:
    """
    Return a sorted list of video paths from two sources:
      1. All video files in VIDEO_DIR (SD card).
      2. Video files in the root directory of each mounted USB drive under
         USB_MOUNT_ROOT.
    SD card videos come first, followed by USB videos grouped by drive name.
    Ordering matters: it is what gives the SD card priority when the same
    filename exists in both places.
    """
    videos = []

    video_dir = Path(VIDEO_DIR)
    if video_dir.exists():
        sd_videos = sorted(
            str(p) for p in video_dir.iterdir()
            if p.is_file() and not p.name.startswith(".")
            and p.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        videos.extend(sd_videos)
    else:
        logger.warning(f"SD card video directory not found: {VIDEO_DIR}")

    usb_root = Path(USB_MOUNT_ROOT)
    if usb_root.exists():
        for drive in sorted(usb_root.iterdir()):
            if not drive.is_dir():
                continue
            try:
                usb_videos = sorted(
                    str(p) for p in drive.iterdir()
                    if p.is_file() and not p.name.startswith(".")
                    and p.suffix.lower() in SUPPORTED_EXTENSIONS
                )
            except (PermissionError, OSError) as exc:
                logger.warning(f"Cannot read USB drive '{drive.name}': {exc}")
                continue
            videos.extend(usb_videos)

    return videos


def usb_drive_name(path: str) -> str | None:
    try:
        return Path(path).relative_to(Path(USB_MOUNT_ROOT)).parts[0]
    except (ValueError, IndexError):
        return None


def video_label(path: str) -> str:
    """Display label for a video path, prefixed with its source."""
    p = Path(path)
    if p.is_relative_to(Path(VIDEO_DIR)):
        return f"[SD Card]  {p.name}"
    drive = usb_drive_name(path)
    if drive:
        return f"[USB: {drive}]  {p.name}"
    return p.name


def resolve_filename(name: str, videos: list[str]) -> str | None:
    """
    Resolve a bare filename to a full path among the discovered videos.
    Exact match first, then case-insensitive, so a filename typed into the
    remote state file as 'Spring.MP4' still finds 'spring.mp4'. SD card wins
    over USB because `videos` is ordered that way.
    """
    if not is_safe_filename(name):
        return None
    for path in videos:
        if Path(path).name == name:
            return path
    lowered = name.lower()
    for path in videos:
        if Path(path).name.lower() == lowered:
            return path
    return None


def find_default_video(videos: list[str]) -> str | None:
    """The fallback video: default.mp4, then default.mov, then whatever is first."""
    for name in DEFAULT_FILES:
        match = resolve_filename(name, videos)
        if match:
            return match
    return videos[0] if videos else None

# ---------------------------------------------------------------------------
# mpv process management
# ---------------------------------------------------------------------------


def launch_mpv(video_path: str) -> subprocess.Popen:
    cmd = [
        "mpv",
        "--loop",
        "--fullscreen",
        "--no-osc",
        "--really-quiet",
        "--vo=gpu",
    ]
    if is_image(video_path):
        # Without this mpv shows a still image for one second and exits, which
        # the crash-loop guard would (correctly) treat as a failure.
        cmd.append("--image-display-duration=inf")
    cmd.append(video_path)

    logger.info(f"Launching: {video_path}")
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill_mpv(proc: subprocess.Popen | None):
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    logger.info("mpv stopped.")

# ---------------------------------------------------------------------------
# The player
# ---------------------------------------------------------------------------


class Player:
    """
    Owns all mutable playback state. Every input source — GPIO buttons, the
    keyboard, and the remote watcher — funnels through these methods on the
    main thread, so there is exactly one writer for `mpv_proc` and friends.

    The central idea is a *target*: the filename that should be playing. The
    target is set by whichever instruction arrived most recently, and
    `reconcile()` closes the gap between the target and what is actually on
    screen. Remote and local instructions are ordered by observation, not by
    clock: a remote instruction is "new" when its fingerprint differs from the
    last one this player has already applied.
    """

    def __init__(self, screen, font, title_font, status_font):
        self.screen      = screen
        self.font        = font
        self.title_font  = title_font
        self.status_font = status_font

        self.videos   = []
        self.selected = 0
        self.state    = AppState.MENU
        self.mpv_proc = None

        # What should be playing, and who asked for it.
        self.target_name   = None     # bare filename; None means "stay stopped"
        self.target_path   = None     # exact path if a local pick named one
        self.target_source = Source.NONE
        self.target_set_at = None

        # What is actually playing.
        self.playing_path    = None
        self.playing_started = None
        self.using_fallback  = False

        # Remote bookkeeping.
        self.last_seen_remote  = None   # fingerprint already applied
        self.remote_video      = None   # filename the remote last asked for
        self.remote_updated    = None   # its timestamp, for humans
        self.remote_checked_at = None
        self.remote_error      = None

        # Media sync bookkeeping.
        self.sync_checked_at = None
        self.sync_error      = None
        self.sync_downloaded = 0

        # Crash-loop protection.
        self.failures = {}
        self.quarantined = set()

        self.needs_draw = False

    # -- persistence --------------------------------------------------------

    def load_state(self):
        """
        Restore state written by a previous run. Persisting `last_seen_remote`
        matters: without it, a reboot would re-apply the last remote
        instruction and clobber a local override made after it.
        """
        path = Path(STATE_FILE)
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"Could not read state file: {exc}")
                return
            self.target_name      = data.get("target_name")
            self.target_path      = data.get("target_path")
            self.target_set_at    = parse_iso(data.get("target_set_at"))
            self.last_seen_remote = data.get("last_seen_remote")
            self.remote_video     = data.get("remote_video")
            self.remote_updated   = parse_iso(data.get("remote_updated"))
            try:
                self.target_source = Source(data.get("target_source", "none"))
            except ValueError:
                self.target_source = Source.NONE
            logger.info(
                f"Restored state: target={self.target_name!r} "
                f"source={self.target_source.value}"
            )
            return

        legacy = Path(LEGACY_STATE_FILE)
        if legacy.exists():
            try:
                stored = legacy.read_text().strip()
            except OSError as exc:
                logger.warning(f"Could not read legacy state file: {exc}")
                return
            if stored:
                self.target_path   = stored
                self.target_name   = Path(stored).name
                self.target_source = Source.LOCAL
                self.target_set_at = utcnow()
                logger.info(f"Migrated legacy state file: {stored}")
                self.save_state()

    def save_state(self):
        data = {
            "target_name":      self.target_name,
            "target_path":      self.target_path,
            "target_source":    self.target_source.value,
            "target_set_at":    self.target_set_at.isoformat() if self.target_set_at else None,
            "last_seen_remote": self.last_seen_remote,
            "remote_video":     self.remote_video,
            "remote_updated":   self.remote_updated.isoformat() if self.remote_updated else None,
        }
        try:
            path = Path(STATE_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            tmp.replace(path)          # atomic: never leave a half-written state
        except OSError as exc:
            logger.warning(f"Could not write state file: {exc}")

    # -- video list ---------------------------------------------------------

    def rescan(self):
        """Refresh the video list, keeping the same item selected if possible."""
        previously = self.videos[self.selected] if self.videos else None
        self.videos = discover_videos()

        if not self.videos:
            self.selected = 0
        elif previously and previously in self.videos:
            self.selected = self.videos.index(previously)
        else:
            self.selected = min(self.selected, len(self.videos) - 1)

    # -- targets ------------------------------------------------------------

    def set_target(self, name, path=None, source=Source.LOCAL):
        """Record a new instruction and act on it immediately."""
        self.target_name   = name
        self.target_path   = path
        self.target_source = source
        self.target_set_at = utcnow()
        # A fresh instruction gets a clean slate on crash-loop bookkeeping.
        self.quarantined.discard(path)
        if name:
            self.failures.pop(name, None)
        self.save_state()
        self.reconcile()

    def resolve_target(self) -> str | None:
        """Turn the current target into a playable path, if it exists locally."""
        if not self.target_name:
            return None
        # A local pick names an exact file; honour it while it still exists.
        if self.target_path and self.target_path in self.videos:
            if self.target_path not in self.quarantined:
                return self.target_path
        match = resolve_filename(self.target_name, self.videos)
        if match and match not in self.quarantined:
            return match
        return None

    def reconcile(self):
        """
        Make what is playing match the target. Safe to call often — it returns
        immediately when reality already matches intent.
        """
        if self.target_name is None:
            # Deliberately stopped by a local EXIT. Stay on the menu until a new
            # instruction arrives.
            return

        desired = self.resolve_target()
        fallback = False

        if desired is None:
            desired = find_default_video(
                [v for v in self.videos if v not in self.quarantined]
            )
            fallback = True
            if desired is None:
                if self.state == AppState.PLAYING:
                    self.stop_playback()
                logger.error(
                    f"Target {self.target_name!r} not found and no fallback "
                    f"video is available."
                )
                return
            logger.warning(
                f"Target {self.target_name!r} not found locally — "
                f"falling back to {Path(desired).name}. "
                f"It will start automatically if the file appears."
            )

        alive = self.mpv_proc is not None and self.mpv_proc.poll() is None
        if self.state == AppState.PLAYING and alive and self.playing_path == desired:
            self.using_fallback = fallback
            return

        self.using_fallback = fallback
        self.start_playback(desired)

    # -- playback -----------------------------------------------------------

    def start_playback(self, path: str):
        kill_mpv(self.mpv_proc)
        self.mpv_proc = None

        if self.state == AppState.MENU:
            hide_pygame_display()
            time.sleep(0.2)

        self.mpv_proc        = launch_mpv(path)
        self.playing_path    = path
        self.playing_started = time.monotonic()
        self.state           = AppState.PLAYING

    def stop_playback(self):
        """Stop mpv and return to the menu."""
        kill_mpv(self.mpv_proc)
        self.mpv_proc     = None
        self.playing_path = None
        if self.state == AppState.PLAYING:
            time.sleep(0.5)               # let mpv release the display
            self.screen = restore_pygame_display()
        self.state = AppState.MENU
        self.rescan()
        self.needs_draw = True

    def handle_mpv_exit(self):
        """
        mpv exited on its own. With --loop that should never happen, so treat it
        as a failure: a corrupt file, or a USB drive pulled mid-playback.
        """
        path    = self.playing_path
        ran_for = time.monotonic() - (self.playing_started or 0)
        self.mpv_proc = None

        if path and ran_for < MPV_MIN_HEALTHY_SEC:
            count = self.failures.get(path, 0) + 1
            self.failures[path] = count
            logger.warning(
                f"mpv exited after {ran_for:.1f}s playing {path} "
                f"(failure {count} of {MPV_MAX_FAILURES})"
            )
            if count >= MPV_MAX_FAILURES:
                logger.error(f"Quarantining unplayable file: {path}")
                self.quarantined.add(path)
        elif path:
            self.failures.pop(path, None)
            logger.info(f"mpv exited after {ran_for:.0f}s. Reconciling.")

        self.playing_path = None
        self.state        = AppState.MENU
        time.sleep(0.5)
        self.screen = restore_pygame_display()
        self.rescan()
        self.needs_draw = True
        self.reconcile()

    # -- local input --------------------------------------------------------

    def step_selection(self, delta: int):
        if not self.videos:
            return
        self.selected = (self.selected + delta) % len(self.videos)
        if self.state == AppState.PLAYING:
            self.play_selected()
        else:
            self.needs_draw = True

    def play_selected(self):
        if not self.videos:
            return
        path = self.videos[self.selected]
        logger.info(f"Local selection: {path}")
        self.set_target(Path(path).name, path=path, source=Source.LOCAL)

    def local_stop(self):
        """
        EXIT button. This is an instruction in its own right — 'show nothing' —
        so it clears the target and wins until the remote state file changes.
        """
        logger.info("Local stop.")
        self.target_name   = None
        self.target_path   = None
        self.target_source = Source.LOCAL
        self.target_set_at = utcnow()
        self.save_state()
        self.stop_playback()

    # -- remote input -------------------------------------------------------

    def handle_remote(self, instruction, error):
        self.remote_checked_at = utcnow()
        self.remote_error      = error

        if instruction is None:
            self.needs_draw = self.state == AppState.MENU
            return

        self.remote_video   = instruction.video
        self.remote_updated = instruction.updated

        if instruction.fingerprint == self.last_seen_remote:
            # Already applied. A local pick made after this instruction stands.
            self.needs_draw = self.state == AppState.MENU
            self.save_state()
            return

        logger.info(
            f"New remote instruction: play {instruction.video!r} "
            f"(set {format_local(instruction.updated)})"
        )
        self.last_seen_remote = instruction.fingerprint
        self.set_target(instruction.video, path=None, source=Source.REMOTE)
        self.needs_draw = self.state == AppState.MENU

    def handle_sync(self, result: dict):
        """React to a completed media sync pass."""
        self.sync_checked_at = utcnow()
        errors = result.get("errors") or []
        self.sync_error = errors[0] if errors else None

        downloaded = result.get("downloaded") or []
        removed    = result.get("removed") or []
        if not downloaded and not removed:
            self.needs_draw = self.state == AppState.MENU
            return

        self.sync_downloaded += len(downloaded)
        logger.info(
            f"Sync complete: {len(downloaded)} downloaded, {len(removed)} removed"
        )

        # A file that was quarantined as unplayable deserves a fresh chance now
        # that its contents have changed.
        for name in downloaded:
            self.quarantined.discard(str(Path(VIDEO_DIR) / name))
            self.failures.pop(str(Path(VIDEO_DIR) / name), None)

        self.rescan()
        self.needs_draw = True

        # If the file currently on screen was replaced, mpv still holds the old
        # copy open — relaunch so the new content actually appears.
        if self.playing_path and Path(self.playing_path).name in downloaded:
            logger.info(f"{Path(self.playing_path).name} changed — restarting playback.")
            self.start_playback(self.playing_path)
            return

        self.reconcile()

    # -- rendering ----------------------------------------------------------

    def status_lines(self) -> list[tuple[str, tuple[int, int, int]]]:
        lines = []

        if self.target_name:
            playing = Path(self.playing_path).name if self.playing_path else "nothing"
            source  = self.target_source.value
            if self.using_fallback:
                lines.append((
                    f"Wanted: {self.target_name} (not found) — playing fallback {playing}",
                    MENU_WARN_COLOR,
                ))
            else:
                lines.append((
                    f"Playing: {playing}  ·  set {source} {format_local(self.target_set_at)}",
                    MENU_STATUS_COLOR,
                ))
        else:
            lines.append(("Stopped locally — waiting for a new instruction",
                          MENU_STATUS_COLOR))

        if self.remote_error:
            lines.append((
                f"Remote: unreachable  ·  last checked {format_local(self.remote_checked_at)}",
                MENU_WARN_COLOR,
            ))
        elif self.remote_video:
            lines.append((
                f"Remote: {self.remote_video}  ·  set {format_local(self.remote_updated)}"
                f"  ·  checked {format_local(self.remote_checked_at)}",
                MENU_STATUS_COLOR,
            ))
        else:
            lines.append(("Remote: not checked yet", MENU_STATUS_COLOR))

        if SYNC_ENABLED:
            if self.sync_error:
                lines.append((f"Sync: {self.sync_error}", MENU_WARN_COLOR))
            elif self.sync_checked_at:
                lines.append((
                    f"Sync: {self.sync_downloaded} file(s) downloaded"
                    f"  ·  checked {format_local(self.sync_checked_at)}",
                    MENU_STATUS_COLOR,
                ))

        return lines

    def render(self):
        screen = self.screen
        screen.fill(MENU_BG_COLOR)

        title = self.title_font.render(
            "VRHS Lobby Monitors Video Selection", True, MENU_TEXT_COLOR
        )
        title_rect = title.get_rect(centerx=screen.get_width() // 2, top=MENU_PADDING)
        screen.blit(title, title_rect)

        if not self.videos:
            msg = self.font.render(
                f"No videos found in {VIDEO_DIR} or {USB_MOUNT_ROOT}",
                True, MENU_ERROR_COLOR,
            )
            screen.blit(msg, msg.get_rect(center=screen.get_rect().center))
        else:
            list_h  = len(self.videos) * MENU_ITEM_HEIGHT
            start_y = max(title_rect.bottom + MENU_PADDING,
                          (screen.get_height() - list_h) // 2)

            for i, path in enumerate(self.videos):
                y = start_y + i * MENU_ITEM_HEIGHT
                item_rect = pygame.Rect(
                    MENU_PADDING, y,
                    screen.get_width() - MENU_PADDING * 2,
                    MENU_ITEM_HEIGHT - 4,
                )
                if i == self.selected:
                    pygame.draw.rect(screen, MENU_HIGHLIGHT_BG, item_rect, border_radius=6)
                    color = MENU_HIGHLIGHT_TEXT
                elif path in self.quarantined:
                    color = MENU_ERROR_COLOR
                else:
                    color = MENU_TEXT_COLOR

                label = video_label(path)
                if path in self.quarantined:
                    label += "  (unplayable)"
                text = self.font.render(label, True, color)
                screen.blit(text, text.get_rect(
                    midleft=(item_rect.left + 12, item_rect.centery)))

        lines  = self.status_lines()
        hint   = "PREV/NEXT or ↑↓ to navigate  |  PLAY or Enter to play  |  Q to quit"
        bottom = screen.get_height() - 16

        rendered = [(self.status_font.render(hint, True, MENU_STATUS_COLOR))]
        for text, color in reversed(lines):
            rendered.append(self.status_font.render(text, True, color))

        for surface in rendered:
            rect = surface.get_rect(centerx=screen.get_width() // 2, bottom=bottom)
            screen.blit(surface, rect)
            bottom -= surface.get_height() + 6

        pygame.display.flip()

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def hide_pygame_display():
    """Shrink the pygame window so mpv can take the full screen."""
    os.environ["SDL_VIDEO_WINDOW_POS"] = "-2,-2"
    pygame.display.set_mode((1, 1), pygame.NOFRAME)


def restore_pygame_display() -> pygame.Surface:
    """Restore pygame to fullscreen after mpv exits."""
    os.environ.pop("SDL_VIDEO_WINDOW_POS", None)
    return pygame.display.set_mode((0, 0), pygame.FULLSCREEN)

# ---------------------------------------------------------------------------
# --check-remote
# ---------------------------------------------------------------------------


def check_remote() -> int:
    """
    Fetch the remote state file once and report what came back, without
    touching the display. This is the quickest way to confirm the web host
    serves the file correctly and is not caching it behind a CDN.
    """
    print(f"Fetching {REMOTE_STATE_URL}\n")
    try:
        raw, etag, info = fetch_remote_state(None)
    except Exception as exc:
        print(f"FAILED: {exc}")
        print("\nThe player would keep playing whatever is on screen.")
        return 1

    print(f"  HTTP status   : {info.get('status')}")
    print(f"  Content-Type  : {info.get('content_type')}")
    print(f"  Cache-Control : {info.get('cache_control')}")
    print(f"  ETag          : {etag}")
    age = info.get("age")
    if age:
        print(f"  Age           : {age}  <-- served from a cache, see below")
    print()

    if raw is None:
        print("Server answered 304 Not Modified.")
        return 0

    print("Body:")
    print(raw.decode("utf-8", errors="replace").strip())
    print()

    try:
        instruction = parse_remote_payload(raw, utcnow())
    except ValueError as exc:
        print(f"INVALID: {exc}")
        return 1

    print(f"  Wants video : {instruction.video}")
    print(f"  Updated     : {format_local(instruction.updated)}"
          f"  (raw: {instruction.updated_raw!r})")
    print(f"  Fingerprint : {instruction.fingerprint}")
    print()

    videos = discover_videos()
    match  = resolve_filename(instruction.video, videos)
    if match:
        print(f"  Resolves to : {match}")
    else:
        fallback = find_default_video(videos)
        print(f"  Resolves to : NOT FOUND among {len(videos)} local video(s)")
        print(f"  Would play  : {fallback or 'nothing — no fallback available'}")

    if age:
        print("\nNote: a non-zero Age header means a cache served this response.")
        print("Edits to the file may take time to reach the Pi.")

    print(f"\nMedia directory: {REMOTE_MEDIA_DIR_URL}")
    try:
        remote_names = list_remote_media()
    except Exception as exc:
        print(f"  FAILED to list: {exc}")
        print("  Media sync would do nothing; playback is unaffected.")
        return 0

    if not remote_names:
        print("  (no media files published)")
        return 0

    dest = Path(VIDEO_DIR)
    for name in remote_names:
        try:
            size, mtime = remote_file_meta(name)
            stale, reason = needs_download(dest / name, size, mtime)
        except Exception as exc:
            print(f"  {name}: could not check ({exc})")
            continue
        marker = "WOULD DOWNLOAD" if stale else "up to date"
        size_mb = f"{size / 1024**2:.1f} MB" if size is not None else "unknown size"
        print(f"  {name}  —  {size_mb}, {format_local(mtime)}  [{marker}: {reason}]")
    return 0


def sync_now() -> int:
    """Run one media sync pass in the foreground and report what happened."""
    print(f"Syncing {REMOTE_MEDIA_DIR_URL}\n  -> {VIDEO_DIR}\n")
    result = sync_once()

    print(f"\nChecked    : {result['checked']} remote file(s)")
    print(f"Downloaded : {len(result['downloaded'])}")
    for name in result["downloaded"]:
        print(f"    {name}")
    if result["removed"]:
        print(f"Removed    : {len(result['removed'])}")
        for name in result["removed"]:
            print(f"    {name}")
    if result["errors"]:
        print(f"Errors     : {len(result['errors'])}")
        for message in result["errors"]:
            print(f"    {message}")
        return 1
    return 0

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    logger.info("Video player starting...")
    time.sleep(2)  # Let the display settle on boot

    pygame.init()
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.display.set_caption("Video Player")
    pygame.mouse.set_visible(False)

    player = Player(
        screen,
        font=pygame.font.SysFont(None, MENU_FONT_SIZE),
        title_font=pygame.font.SysFont(None, MENU_TITLE_FONT_SIZE),
        status_font=pygame.font.SysFont(None, MENU_STATUS_FONT_SIZE),
    )
    clock = pygame.time.Clock()

    setup_gpio()

    player.rescan()
    player.load_state()

    # Nothing remembered? Fall back to the default video so a fresh install
    # still comes up playing something.
    if player.target_name is None and player.target_source is Source.NONE:
        default = find_default_video(player.videos)
        if default:
            player.set_target(Path(default).name, path=default, source=Source.FALLBACK)
    else:
        player.reconcile()

    if player.state == AppState.MENU:
        player.render()

    watcher = RemoteWatcher()
    watcher.start()

    syncer = SyncWorker() if SYNC_ENABLED else None
    if syncer:
        syncer.start()

    pygame.time.set_timer(pygame.USEREVENT, MPV_POLL_INTERVAL_MS)
    pygame.time.set_timer(EVT_RESCAN, RESCAN_INTERVAL_MS)

    running = True
    while running:
        for event in pygame.event.get():

            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.USEREVENT:
                if (player.state == AppState.PLAYING
                        and player.mpv_proc
                        and player.mpv_proc.poll() is not None):
                    player.handle_mpv_exit()

            elif event.type == EVT_RESCAN:
                before = player.videos
                player.rescan()
                if player.videos != before:
                    logger.info("Video list changed.")
                    player.needs_draw = True
                    # A file the remote asked for may have just been plugged in.
                    player.reconcile()

            elif event.type == EVT_REMOTE:
                player.handle_remote(event.instruction, event.error)

            elif event.type == EVT_SYNC:
                player.handle_sync({
                    "downloaded": event.downloaded,
                    "removed":    event.removed,
                    "errors":     event.errors,
                    "checked":    event.checked,
                })

            elif event.type == EVT_BTN_EXIT:
                if player.state == AppState.PLAYING:
                    player.local_stop()

            elif event.type == EVT_BTN_PREV:
                player.step_selection(-1)

            elif event.type == EVT_BTN_NEXT:
                player.step_selection(+1)

            elif event.type == EVT_BTN_PLAY:
                if player.state == AppState.MENU:
                    player.play_selected()

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    if player.state == AppState.PLAYING:
                        player.local_stop()
                    else:
                        running = False
                elif event.key == pygame.K_UP and player.state == AppState.MENU:
                    player.step_selection(-1)
                elif event.key == pygame.K_DOWN and player.state == AppState.MENU:
                    player.step_selection(+1)
                elif event.key == pygame.K_RETURN and player.state == AppState.MENU:
                    player.play_selected()

        if player.needs_draw and player.state == AppState.MENU:
            player.render()
            player.needs_draw = False

        clock.tick(30)

    watcher.stop()
    if syncer:
        syncer.stop()
    kill_mpv(player.mpv_proc)
    cleanup_gpio()
    pygame.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VRHS lobby screen video player")
    parser.add_argument(
        "--check-remote", action="store_true",
        help="report on the remote state file and media directory, then exit",
    )
    parser.add_argument(
        "--sync-now", action="store_true",
        help="download any new or changed media files now, then exit",
    )
    args = parser.parse_args()

    if args.check_remote:
        sys.exit(check_remote())

    if args.sync_now:
        sys.exit(sync_now())

    try:
        main()
    except Exception as exc:
        logger.exception(f"Unexpected error: {exc}")
        sys.exit(1)
