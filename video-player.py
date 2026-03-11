#!/usr/bin/env python3
"""
Raspberry Pi Interactive Video Player
- Fullscreen pygame menu with GPIO button support
- State persistence (remembers last played video across reboots)
- mpv launched as a non-blocking subprocess

GPIO buttons (BCM numbering, wire each between pin and GND):
  Pin 17 = EXIT  — stop video, return to menu
  Pin 27 = PREV  — previous item in menu
  Pin 22 = NEXT  — next item in menu
  Pin 23 = PLAY  — play selected video

Keyboard fallback (for testing without GPIO):
  Up/Down arrows = navigate menu
  Enter          = play selected video
  Q              = return to menu (while playing) or quit app (on menu)
"""

import os
import sys
import subprocess
import time
import logging
from pathlib import Path
from enum import Enum, auto

import pygame

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VIDEO_DIR = "/home/pi/videos"
USB_MOUNT_ROOT = "/media/pi"
STATE_FILE = "/home/pi/.config/video-player/last_played.txt"
DEFAULT_FILES = ["default.mp4", "default.mov"]
SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

# GPIO BCM pin numbers
PIN_EXIT = 17
PIN_PREV = 27
PIN_NEXT = 22
PIN_PLAY = 23

BUTTON_DEBOUNCE_MS = 300

# Menu appearance
MENU_BG_COLOR       = (10, 10, 10)
MENU_TEXT_COLOR     = (220, 220, 220)
MENU_HIGHLIGHT_BG   = (50, 100, 180)
MENU_HIGHLIGHT_TEXT = (255, 255, 255)
MENU_FONT_SIZE      = 36
MENU_TITLE_FONT_SIZE = 48
MENU_ITEM_HEIGHT    = 50
MENU_PADDING        = 40

# How often (ms) to check if mpv has exited on its own
MPV_POLL_INTERVAL_MS = 250

# How often (ms) to re-scan for new/removed video files while on the menu
RESCAN_INTERVAL_MS = 5000

# ---------------------------------------------------------------------------
# Custom pygame event types (posted from GPIO callbacks)
# ---------------------------------------------------------------------------

EVT_BTN_EXIT = pygame.USEREVENT + 1
EVT_BTN_PREV = pygame.USEREVENT + 2
EVT_BTN_NEXT = pygame.USEREVENT + 3
EVT_BTN_PLAY = pygame.USEREVENT + 4
EVT_RESCAN   = pygame.USEREVENT + 5

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AppState(Enum):
    MENU    = auto()
    PLAYING = auto()

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
# State persistence
# ---------------------------------------------------------------------------


def load_last_played() -> str | None:
    try:
        p = Path(STATE_FILE)
        if p.exists():
            stored = p.read_text().strip()
            if stored and Path(stored).is_file():
                return stored
    except Exception as exc:
        logger.warning(f"Could not read state file: {exc}")
    return None


def save_last_played(video_path: str):
    try:
        Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(STATE_FILE).write_text(video_path)
    except Exception as exc:
        logger.warning(f"Could not write state file: {exc}")

# ---------------------------------------------------------------------------
# Video discovery
# ---------------------------------------------------------------------------


def discover_videos() -> list[str]:
    """
    Return a sorted list of video paths from two sources:
      1. All video files in VIDEO_DIR (SD card).
      2. Video files in the root directory of each mounted USB drive under USB_MOUNT_ROOT.
    SD card videos come first, followed by USB videos grouped by drive name.
    """
    videos = []

    # SD card
    video_dir = Path(VIDEO_DIR)
    if video_dir.exists():
        sd_videos = sorted(
            str(p) for p in video_dir.iterdir()
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in SUPPORTED_EXTENSIONS
        )
        videos.extend(sd_videos)
        logger.info(f"SD card: {len(sd_videos)} video(s) found in {VIDEO_DIR}")
    else:
        logger.warning(f"SD card video directory not found: {VIDEO_DIR}")

    # USB drives — root directory only (not recursive)
    usb_root = Path(USB_MOUNT_ROOT)
    if usb_root.exists():
        for drive in sorted(usb_root.iterdir()):
            if not drive.is_dir():
                continue
            try:
                usb_videos = sorted(
                    str(p) for p in drive.iterdir()
                    if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in SUPPORTED_EXTENSIONS
                )
            except PermissionError:
                logger.warning(f"Permission denied accessing USB drive '{drive.name}', skipping.")
                continue
            if usb_videos:
                logger.info(f"USB drive '{drive.name}': {len(usb_videos)} video(s) found")
                videos.extend(usb_videos)

    logger.info(f"Total: {len(videos)} video(s) discovered")
    return videos


def video_label(path: str) -> str:
    """Return a display label for a video path, prefixed with its source."""
    p = Path(path)
    if p.is_relative_to(Path(VIDEO_DIR)):
        return f"[SD Card]  {p.name}"
    usb_root = Path(USB_MOUNT_ROOT)
    try:
        drive_name = p.relative_to(usb_root).parts[1]  # /media/pi/<DRIVE_NAME>/file
        return f"[USB]  {p.name}"
    except (ValueError, IndexError):
        return p.name


def find_default_video(videos: list[str]) -> str | None:
    video_dir = Path(VIDEO_DIR)
    for name in DEFAULT_FILES:
        candidate = str(video_dir / name)
        if candidate in videos:
            return candidate
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
        video_path,
    ]
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
# Display helpers
# ---------------------------------------------------------------------------


def hide_pygame_display():
    """Shrink pygame window so mpv can take the full screen."""
    os.environ["SDL_VIDEO_WINDOW_POS"] = "-2,-2"
    pygame.display.set_mode((1, 1), pygame.NOFRAME)


def restore_pygame_display() -> pygame.Surface:
    """Restore pygame to fullscreen after mpv exits."""
    os.environ.pop("SDL_VIDEO_WINDOW_POS", None)
    return pygame.display.set_mode((0, 0), pygame.FULLSCREEN)

# ---------------------------------------------------------------------------
# Menu rendering
# ---------------------------------------------------------------------------


def render_menu(screen, videos: list[str], selected: int, font, title_font):
    screen.fill(MENU_BG_COLOR)

    title = title_font.render("VRHS Lobby Monitors Video Selection", True, MENU_TEXT_COLOR)
    title_rect = title.get_rect(centerx=screen.get_width() // 2, top=MENU_PADDING)
    screen.blit(title, title_rect)

    if not videos:
        msg = font.render(f"No videos found in {VIDEO_DIR} or {USB_MOUNT_ROOT}", True, (200, 80, 80))
        screen.blit(msg, msg.get_rect(center=screen.get_rect().center))
        pygame.display.flip()
        return

    list_h = len(videos) * MENU_ITEM_HEIGHT
    start_y = max(title_rect.bottom + MENU_PADDING, (screen.get_height() - list_h) // 2)

    for i, path in enumerate(videos):
        y = start_y + i * MENU_ITEM_HEIGHT
        item_rect = pygame.Rect(
            MENU_PADDING, y,
            screen.get_width() - MENU_PADDING * 2,
            MENU_ITEM_HEIGHT - 4,
        )
        if i == selected:
            pygame.draw.rect(screen, MENU_HIGHLIGHT_BG, item_rect, border_radius=6)
            color = MENU_HIGHLIGHT_TEXT
        else:
            color = MENU_TEXT_COLOR

        label = font.render(video_label(path), True, color)
        screen.blit(label, label.get_rect(midleft=(item_rect.left + 12, item_rect.centery)))

    hint = font.render(
        "PREV/NEXT or ↑↓ to navigate  |  PLAY or Enter to play  |  Q to quit",
        True, (100, 100, 100),
    )
    screen.blit(hint, hint.get_rect(centerx=screen.get_width() // 2, bottom=screen.get_height() - 16))

    pygame.display.flip()

# ---------------------------------------------------------------------------
# Video list helpers
# ---------------------------------------------------------------------------


def rescan(current_videos: list[str], selected: int) -> tuple[list[str], int]:
    """
    Re-discover videos and return the updated list with a best-effort selected index.
    Tries to keep the same video selected; falls back to clamping to the list end.
    """
    previously_selected = current_videos[selected] if current_videos else None
    new_videos = discover_videos()

    if not new_videos:
        return new_videos, 0

    if previously_selected and previously_selected in new_videos:
        new_selected = new_videos.index(previously_selected)
    else:
        new_selected = min(selected, len(new_videos) - 1)

    return new_videos, new_selected


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    logger.info("Video player starting...")
    time.sleep(2)  # Let display settle on boot

    pygame.init()
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.display.set_caption("Video Player")
    pygame.mouse.set_visible(False)

    font       = pygame.font.SysFont(None, MENU_FONT_SIZE)
    title_font = pygame.font.SysFont(None, MENU_TITLE_FONT_SIZE)
    clock      = pygame.time.Clock()

    setup_gpio()

    videos   = discover_videos()
    selected = 0
    state    = AppState.MENU
    mpv_proc = None

    # Auto-play on startup: prefer last-played, fall back to default.mov on SD card
    auto_play = None
    last = load_last_played()
    if last and last in videos:
        auto_play = last
        selected  = videos.index(last)
    else:
        fallback = find_default_video(videos)
        if fallback:
            auto_play = fallback
            selected  = videos.index(fallback) if fallback in videos else 0

    if auto_play:
        logger.info(f"Auto-playing: {auto_play}")
        save_last_played(auto_play)
        hide_pygame_display()
        time.sleep(0.2)
        mpv_proc = launch_mpv(auto_play)
        state = AppState.PLAYING
    else:
        render_menu(screen, videos, selected, font, title_font)

    # Timer to poll mpv process status
    pygame.time.set_timer(pygame.USEREVENT, MPV_POLL_INTERVAL_MS)
    # Timer to periodically re-scan for new/removed video files
    pygame.time.set_timer(EVT_RESCAN, RESCAN_INTERVAL_MS)

    running     = True
    needs_draw  = False

    while running:
        for event in pygame.event.get():

            if event.type == pygame.QUIT:
                running = False

            # --- mpv exit poll ---
            elif event.type == pygame.USEREVENT:
                if state == AppState.PLAYING and mpv_proc and mpv_proc.poll() is not None:
                    logger.info("mpv exited naturally. Returning to menu.")
                    mpv_proc = None
                    state    = AppState.MENU
                    time.sleep(0.5)
                    screen   = restore_pygame_display()
                    videos, selected = rescan(videos, selected)
                    needs_draw = True

            # --- Periodic rescan while on menu ---
            elif event.type == EVT_RESCAN:
                if state == AppState.MENU:
                    new_videos, new_selected = rescan(videos, selected)
                    if new_videos != videos:
                        logger.info("Video list changed, refreshing menu.")
                        videos, selected = new_videos, new_selected
                        needs_draw = True

            # --- EXIT button ---
            elif event.type == EVT_BTN_EXIT:
                if state == AppState.PLAYING:
                    kill_mpv(mpv_proc)
                    mpv_proc = None
                    state    = AppState.MENU
                    time.sleep(0.5)
                    screen   = restore_pygame_display()
                    videos, selected = rescan(videos, selected)
                    needs_draw = True

            # --- PREV button ---
            elif event.type == EVT_BTN_PREV:
                if videos:
                    selected = (selected - 1) % len(videos)
                    if state == AppState.PLAYING:
                        kill_mpv(mpv_proc)
                        save_last_played(videos[selected])
                        mpv_proc = launch_mpv(videos[selected])
                    else:
                        needs_draw = True

            # --- NEXT button ---
            elif event.type == EVT_BTN_NEXT:
                if videos:
                    selected = (selected + 1) % len(videos)
                    if state == AppState.PLAYING:
                        kill_mpv(mpv_proc)
                        save_last_played(videos[selected])
                        mpv_proc = launch_mpv(videos[selected])
                    else:
                        needs_draw = True

            # --- PLAY button ---
            elif event.type == EVT_BTN_PLAY:
                if state == AppState.MENU and videos:
                    video = videos[selected]
                    save_last_played(video)
                    hide_pygame_display()
                    time.sleep(0.2)
                    mpv_proc = launch_mpv(video)
                    state    = AppState.PLAYING

            # --- Keyboard fallback ---
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    if state == AppState.PLAYING:
                        kill_mpv(mpv_proc)
                        mpv_proc = None
                        state    = AppState.MENU
                        screen   = restore_pygame_display()
                        videos, selected = rescan(videos, selected)
                        needs_draw = True
                    else:
                        running = False

                elif event.key == pygame.K_UP and state == AppState.MENU and videos:
                    selected = (selected - 1) % len(videos)
                    needs_draw = True

                elif event.key == pygame.K_DOWN and state == AppState.MENU and videos:
                    selected = (selected + 1) % len(videos)
                    needs_draw = True

                elif event.key == pygame.K_RETURN and state == AppState.MENU and videos:
                    video = videos[selected]
                    save_last_played(video)
                    hide_pygame_display()
                    time.sleep(0.2)
                    mpv_proc = launch_mpv(video)
                    state    = AppState.PLAYING

        if needs_draw and state == AppState.MENU:
            render_menu(screen, videos, selected, font, title_font)
            needs_draw = False

        clock.tick(30)

    kill_mpv(mpv_proc)
    cleanup_gpio()
    pygame.quit()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception(f"Unexpected error: {exc}")
        sys.exit(1)
