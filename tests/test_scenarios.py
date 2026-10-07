#!/usr/bin/env python3
"""
End-to-end reconciliation scenarios, with mpv and the display stubbed out.

These cover the rule that motivated the whole design: the most recent
instruction wins, whether it came from the website or from a button in the
lobby — decided by change detection, never by comparing clocks.

Run with:  python3 tests/test_scenarios.py
"""
import os
import sys
import json
import time
import logging
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import load_player, Results

vp = load_player()
r = Results()
logging.disable(logging.WARNING)      # keep the scenario output readable

tmp = tempfile.mkdtemp()
vp.STATE_FILE = os.path.join(tmp, "state.json")
vp.LEGACY_STATE_FILE = os.path.join(tmp, "legacy.txt")
vp.EVENTS_FILE = os.path.join(tmp, "events.json")

SD = "/home/pi/videos/"
LIBRARY = [SD + "default.mp4", SD + "A.mp4", SD + "B.mp4", SD + "C.mp4"]

launched = []


class FakeProc:
    def poll(self):
        return None          # always "still running"


vp.launch_mpv = lambda path: (launched.append(path), FakeProc())[1]
vp.kill_mpv = lambda proc: None
vp.hide_pygame_display = lambda: None
vp.restore_pygame_display = lambda: None
vp.time.sleep = lambda seconds: None   # don't wait on display transitions


def new_player(library=LIBRARY):
    """Construct a player over a fixed library, loading any persisted state."""
    vp.discover_videos = lambda: list(library)
    player = vp.Player(None, None, None, None)
    player.rescan()
    player.load_state()
    return player


def fresh_state():
    if os.path.exists(vp.STATE_FILE):
        os.remove(vp.STATE_FILE)


def remote(video, updated, version=1):
    """Build the instruction a successful poll would produce."""
    payload = {"version": version, "video": video, "updated": updated}
    return vp.parse_remote_payload(json.dumps(payload).encode(), vp.utcnow())


def playing(player):
    return os.path.basename(player.playing_path) if player.playing_path else None


print("=== Scenario 1: the 8:00 / 8:05 / 8:06 / 9:00 walkthrough ===")
fresh_state()
p = new_player()

p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)      # 8:00 AM CDT
r.check("8:00 remote selects A", playing(p), "A.mp4")

p.selected = p.videos.index(SD + "B.mp4")                            # 8:05 AM
p.play_selected()
r.check("8:05 local selects B", playing(p), "B.mp4")
r.check("     instruction source is local", p.target_source, vp.Source.LOCAL)

# The case the whole design exists for: an unchanged poll must not revert B.
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)      # 8:06 AM
r.check("8:06 unchanged poll leaves B alone", playing(p), "B.mp4")
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
r.check("8:07 and 8:08 still B", playing(p), "B.mp4")

p.handle_remote(remote("C.mp4", "2026-08-12T14:00:00Z"), None)      # 9:00 AM
r.check("9:00 new remote instruction wins", playing(p), "C.mp4")
r.check("     instruction source is remote", p.target_source, vp.Source.REMOTE)

print("\n=== Scenario 2: re-assert the same video by bumping the timestamp ===")
fresh_state()
p = new_player()
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
p.selected = p.videos.index(SD + "B.mp4")
p.play_selected()
r.check("local override in effect", playing(p), "B.mp4")
p.handle_remote(remote("A.mp4", "2026-08-12T15:30:00Z"), None)
r.check("same video, new timestamp, wins", playing(p), "A.mp4")

print("\n=== Scenario 3: a reboot preserves the local override ===")
fresh_state()
p = new_player()
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
p.selected = p.videos.index(SD + "B.mp4")
p.play_selected()
r.check("before reboot", playing(p), "B.mp4")

rebooted = new_player()               # fresh object, same state file
rebooted.reconcile()
r.check("after reboot resumes B", playing(rebooted), "B.mp4")
rebooted.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
r.check("already-seen remote does not clobber", playing(rebooted), "B.mp4")
rebooted.handle_remote(remote("C.mp4", "2026-08-12T16:00:00Z"), None)
r.check("a genuinely new remote still wins", playing(rebooted), "C.mp4")

print("\n=== Scenario 4: missing file falls back, then switches when it appears ===")
fresh_state()
small = [SD + "default.mp4", SD + "A.mp4"]
p = new_player(small)
p.handle_remote(remote("gala-2026.mp4", "2026-08-12T13:00:00Z"), None)
r.check("missing target plays default", playing(p), "default.mp4")
r.check("     marked as fallback", p.using_fallback, True)
r.check("     still wants the real target", p.target_name, "gala-2026.mp4")

vp.discover_videos = lambda: small + ["/media/pi/STICK/gala-2026.mp4"]
p.rescan()
p.reconcile()
r.check("USB plugged in, target starts", playing(p), "gala-2026.mp4")
r.check("     no longer a fallback", p.using_fallback, False)

print("\n=== Scenario 5: an unplayable file is quarantined, not looped on ===")
fresh_state()
p = new_player()
p.handle_remote(remote("C.mp4", "2026-08-12T13:00:00Z"), None)
r.check("playing C", playing(p), "C.mp4")
for _ in range(vp.MPV_MAX_FAILURES):
    p.playing_started = time.monotonic()      # mpv died immediately
    p.handle_mpv_exit()
r.check("quarantined after repeated fast exits", SD + "C.mp4" in p.quarantined, True)
r.check("fell back to default", playing(p), "default.mp4")

p.handle_remote(remote("A.mp4", "2026-08-12T17:00:00Z"), None)
p.playing_started = time.monotonic() - 3600   # ran happily for an hour
p.handle_mpv_exit()
r.check("a long run is not a failure", SD + "A.mp4" in p.quarantined, False)
r.check("and it restarts", playing(p), "A.mp4")

print("\n=== Scenario 6: local EXIT is itself an instruction ===")
fresh_state()
p = new_player()
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
p.local_stop()
r.check("EXIT stops playback", playing(p), None)
r.check("     returns to the menu", p.state, vp.AppState.MENU)
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
r.check("unchanged poll stays stopped", playing(p), None)
p.reconcile()
r.check("reconcile stays stopped", playing(p), None)
p.handle_remote(remote("C.mp4", "2026-08-12T18:00:00Z"), None)
r.check("a new remote instruction resumes", playing(p), "C.mp4")

print("\n=== Scenario 7: outages and bad payloads never disturb playback ===")
fresh_state()
p = new_player()
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
before = playing(p)
p.handle_remote(None, "Network is unreachable")
r.check("network outage keeps playing", playing(p), before)
r.check("     error kept for display", p.remote_error, "Network is unreachable")
p.handle_remote(None, None)
r.check("304 Not Modified keeps playing", playing(p), before)
p.handle_remote(None, "not valid JSON")
r.check("malformed file keeps playing", playing(p), before)

print("\n=== Scenario 8: agreeing polls cause no restarts ===")
fresh_state()
p = new_player()
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
launched.clear()
for _ in range(10):
    p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
    p.reconcile()
r.check("ten polls, zero relaunches", len(launched), 0)

print("\n=== Scenario 9: replacing the file on screen restarts playback ===")
fresh_state()
p = new_player()
p.handle_remote(remote("default.mp4", "2026-08-12T13:00:00Z"), None)
r.check("playing default.mp4", playing(p), "default.mp4")
launched.clear()
# The sync replaced the very file mpv has open. mpv keeps the old inode, so
# without a relaunch the screen would keep showing the previous content.
p.handle_sync({"downloaded": ["default.mp4"], "removed": [], "errors": [], "checked": 1})
r.check("relaunched mpv", len(launched), 1)
r.check("same file, new content", playing(p), "default.mp4")

print("\n=== Scenario 10: an unrelated download doesn't interrupt playback ===")
launched.clear()
p.handle_sync({"downloaded": ["B.mp4"], "removed": [], "errors": [], "checked": 2})
r.check("no relaunch", len(launched), 0)
r.check("still playing", playing(p), "default.mp4")

print("\n=== Scenario 11: syncing the missing target starts it automatically ===")
fresh_state()
small = [SD + "default.mp4"]
p = new_player(small)
p.handle_remote(remote("gala.mp4", "2026-08-12T13:00:00Z"), None)
r.check("target missing, plays default", playing(p), "default.mp4")
# The sync downloads it; the file list now includes it.
vp.discover_videos = lambda: small + [SD + "gala.mp4"]
p.handle_sync({"downloaded": ["gala.mp4"], "removed": [], "errors": [], "checked": 2})
r.check("downloaded target starts playing", playing(p), "gala.mp4")
r.check("no longer a fallback", p.using_fallback, False)

print("\n=== Scenario 12: a replaced file gets out of quarantine ===")
fresh_state()
p = new_player()
p.handle_remote(remote("C.mp4", "2026-08-12T13:00:00Z"), None)
for _ in range(vp.MPV_MAX_FAILURES):
    p.playing_started = time.monotonic()
    p.handle_mpv_exit()
r.check("quarantined while broken", SD + "C.mp4" in p.quarantined, True)
# A new copy arrives — the old verdict shouldn't stick to different content.
p.handle_sync({"downloaded": ["C.mp4"], "removed": [], "errors": [], "checked": 1})
r.check("quarantine cleared", SD + "C.mp4" in p.quarantined, False)

print("\n=== Scenario 14: Q pressed in mpv returns to the menu ===")
fresh_state()
p = new_player()
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
p.playing_started = time.monotonic() - 60
p.mpv_proc.returncode = 0                     # mpv's clean quit
p.handle_mpv_exit()
r.check("not relaunched", playing(p), None)
r.check("     back on the menu", p.state, vp.AppState.MENU)
r.check("     not counted as a failure", p.failures, {})
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
r.check("unchanged poll stays stopped", playing(p), None)

p.handle_remote(remote("B.mp4", "2026-08-12T14:00:00Z"), None)
p.playing_started = time.monotonic() - 60
p.mpv_proc.returncode = 2                     # mpv failed to play the file
p.handle_mpv_exit()
r.check("an error exit still relaunches", playing(p), "B.mp4")

print("\n=== Scenario 15: a restart resumes the last video, even after EXIT ===")
fresh_state()
p = new_player()
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
p.selected = p.videos.index(SD + "B.mp4")
p.play_selected()
p.local_stop()
r.check("stopped before restart", playing(p), None)
rebooted = new_player()
rebooted.resume_on_startup()
r.check("restart resumes B", playing(rebooted), "B.mp4")
rebooted.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
r.check("already-seen remote does not clobber", playing(rebooted), "B.mp4")
rebooted.local_stop()
again = new_player()
again.resume_on_startup()
r.check("resumes again after a second stop", playing(again), "B.mp4")

fresh_state()
p = new_player()
p.resume_on_startup()
r.check("fresh install plays the default", playing(p), "default.mp4")

print("\n=== Scenario 16: the webcam is a live source like any file ===")
CAM = "/dev/v4l/by-id/usb-MOKOSE_UVC_Camera-video-index0"
with_cam = LIBRARY + [CAM]
fresh_state()
p = new_player(with_cam)
r.check("webcam is in the menu", CAM in p.videos, True)
r.check("     labelled as live", vp.video_label(CAM), "[Live]  Webcam")
r.check("     never the fallback", vp.find_default_video(p.videos), SD + "default.mp4")
p.handle_remote(remote("webcam", "2026-10-02T13:00:00Z"), None)
r.check("remote 'webcam' plays the camera", p.playing_path, CAM)
r.check("     shown by name", p.status_lines()[0][0].startswith("Playing: webcam"), True)

# Unplugged mid-show: the device node disappears, mpv exits.
vp.discover_videos = lambda: list(LIBRARY)
p.rescan()
p.playing_started = time.monotonic() - 600
p.mpv_proc.returncode = 0          # whatever mpv reports, the camera is gone
p.handle_mpv_exit()
r.check("unplugged camera falls back to default", playing(p), "default.mp4")   # no file played yet
r.check("     still wants the webcam", p.target_name, "webcam")

# Plugged back in: picked up by the next rescan.
vp.discover_videos = lambda: list(with_cam)
p.rescan()
p.reconcile()
r.check("replugged camera resumes", p.playing_path, CAM)

# Fast failures (camera present but mpv can't open it) quarantine it...
for _ in range(vp.MPV_MAX_FAILURES):
    p.playing_started = time.monotonic()
    p.mpv_proc.returncode = 2
    p.handle_mpv_exit()
r.check("repeated fast failures quarantine the camera", CAM in p.quarantined, True)
r.check("     and fall back", playing(p), "default.mp4")
# ...but unplug and replug gives it a fresh start.
vp.discover_videos = lambda: list(LIBRARY)
p.rescan()
vp.discover_videos = lambda: list(with_cam)
p.rescan()
p.reconcile()
r.check("replug clears the quarantine", (CAM in p.quarantined, p.playing_path), (False, CAM))

# q in mpv while the camera is still there is a normal local stop.
real_exists = vp.os.path.exists
vp.os.path.exists = lambda path: path == CAM or real_exists(path)
p.playing_started = time.monotonic() - 60
p.mpv_proc.returncode = 0
p.handle_mpv_exit()
vp.os.path.exists = real_exists
r.check("q on a live camera returns to the menu", (playing(p), p.state), (None, vp.AppState.MENU))

# Picked from the menu, it's remembered by name across a restart.
fresh_state()
p = new_player(with_cam)
p.selected = p.videos.index(CAM)
p.play_selected()
r.check("menu pick targets 'webcam'", p.target_name, "webcam")
rebooted = new_player(with_cam)
rebooted.resume_on_startup()
r.check("restart resumes the webcam", rebooted.playing_path, CAM)

print("\n=== Scenario 17: a missing webcam falls back to the most recent video ===")
fresh_state()
p = new_player(LIBRARY)                       # no camera plugged in
p.handle_remote(remote("B.mp4", "2026-10-06T13:00:00Z"), None)
p.handle_remote(remote("webcam", "2026-10-06T14:00:00Z"), None)
r.check("webcam selected while absent keeps B", playing(p), "B.mp4")
r.check("     still wants the webcam", p.target_name, "webcam")
vp.discover_videos = lambda: list(with_cam)
p.rescan()
p.reconcile()
r.check("plugging it in goes live", p.playing_path, CAM)
vp.discover_videos = lambda: list(LIBRARY)
p.rescan()
p.playing_started = time.monotonic() - 600
p.mpv_proc.returncode = 0
p.handle_mpv_exit()
r.check("unplugging it goes back to B", playing(p), "B.mp4")

# A menu pick counts too, and the choice survives a restart.
p.selected = p.videos.index(SD + "C.mp4")
p.play_selected()
p.handle_remote(remote("webcam", "2026-10-06T15:00:00Z"), None)
r.check("local pick is the most recent video", playing(p), "C.mp4")
rebooted = new_player(LIBRARY)
rebooted.resume_on_startup()
r.check("     remembered across a restart", playing(rebooted), "C.mp4")

# The most recent video gone too: the default plays.
rebooted = new_player([SD + "default.mp4", SD + "A.mp4"])
rebooted.resume_on_startup()
r.check("most recent video missing plays the default", playing(rebooted), "default.mp4")

# State files written before this existed fall back on the last target.
state = json.loads(open(vp.STATE_FILE).read())
state.update(target_name="webcam", target_path=None, last_target_name="A.mp4",
             last_target_path=SD + "A.mp4")
del state["last_file_name"], state["last_file_path"]
open(vp.STATE_FILE, "w").write(json.dumps(state))
old = new_player(LIBRARY)
old.resume_on_startup()
r.check("old state file migrates", playing(old), "A.mp4")

print("\n=== Scenario 13: sync errors are surfaced but harmless ===")
fresh_state()
p = new_player()
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
before = playing(p)
p.handle_sync({"downloaded": [], "removed": [], "errors": ["boom"], "checked": 0})
r.check("playback unaffected", playing(p), before)
r.check("error kept for display", p.sync_error, "boom")

print("\n=== Scenario 18: status reports say what is on screen and available ===")
fresh_state()
media_root = tempfile.mkdtemp()
saved_dirs = (vp.VIDEO_DIR, vp.USB_MOUNT_ROOT)
vp.VIDEO_DIR = os.path.join(media_root, "videos")
vp.USB_MOUNT_ROOT = os.path.join(media_root, "media")
os.makedirs(os.path.join(vp.USB_MOUNT_ROOT, "STICK"))
os.makedirs(vp.VIDEO_DIR)
files = [os.path.join(vp.VIDEO_DIR, "default.mp4"), os.path.join(vp.VIDEO_DIR, "poster.png"),
         os.path.join(vp.USB_MOUNT_ROOT, "STICK", "show.mov")]
for i, f in enumerate(files):
    open(f, "wb").write(b"x" * (100 * (i + 1)))
CAM = "/dev/v4l/by-id/usb-Cam-video-index0"

p = new_player(files + [CAM])
p.handle_remote(remote("show.mov", "2026-08-12T13:00:00Z"), None)
report = p.status_report()
r.check("schema version", report["version"], 1)
r.check("playing a file", (report["player"]["mode"], report["player"]["showing"],
                           report["player"]["location"]), ("playing", "show.mov", "usb:STICK"))
r.check("asked for remotely", (report["player"]["wanted"], report["player"]["wanted_from"]),
        ("show.mov", "remote"))
r.check("lists every file, not the camera", [(m["name"], m["location"], m["bytes"]) for m in report["media"]],
        [("default.mp4", "sd", 100), ("poster.png", "sd", 200), ("show.mov", "usb:STICK", 300)])
r.check("knows an image from a video", [m["kind"] for m in report["media"]], ["video", "image", "video"])
r.check("webcam available", (report["webcam"]["available"], report["webcam"]["device"]),
        (True, "usb-Cam-video-index0"))
r.check("report is plain JSON", json.loads(json.dumps(report)) == report, True)

p.handle_remote(remote("webcam", "2026-08-12T14:00:00Z"), None)
report = p.status_report()
r.check("showing the webcam", (report["player"]["mode"], report["player"]["showing"]), ("webcam", "webcam"))

sig = p.status_signature()
p.videos = files                                   # camera unplugged
p.reconcile()
r.check("unplugging changes the signature", p.status_signature() != sig, True)
report = p.status_report()
r.check("webcam gone", report["webcam"]["available"], False)
r.check("     falls back to the last video", (report["player"]["showing"], report["player"]["fallback"]),
        ("show.mov", True))

p.local_stop()
report = p.status_report()
r.check("menu after EXIT", (report["player"]["mode"], report["player"]["showing"]), ("menu", None))
vp.VIDEO_DIR, vp.USB_MOUNT_ROOT = saved_dirs

print("\n=== Scenario 19: things done at the Pi itself are logged ===")
fresh_state()
if os.path.exists(vp.EVENTS_FILE):
    os.remove(vp.EVENTS_FILE)
kinds = lambda player: [(e["kind"], e["detail"]) for e in player.events.items]

# Startup: a new boot ID means the Pi started; the same one, only the app.
vp.boot_id = lambda: "boot-A"
real_uptime, vp.uptime = vp.uptime, lambda: 40.0
p = new_player()
p.events.log_startup()
r.check("first run soon after boot is a boot", kinds(p)[-1], ("boot", "power-on or reboot"))
os.remove(vp.EVENTS_FILE)
vp.uptime = lambda: 86400.0
p = new_player()
p.events.log_startup()
r.check("first run a day after boot is a restart", kinds(p)[-1], ("restart", ""))
vp.uptime = real_uptime
p = new_player()
p.events.log_startup()
r.check("same boot: the app restarted", kinds(p)[-1], ("restart", ""))
vp.boot_id = lambda: "boot-B"
p = new_player()
p.events.log_startup()
r.check("new boot: the Pi started", kinds(p)[-1], ("boot", "power-on or reboot"))
r.check("sequence numbers carry on across restarts", [e["seq"] for e in p.events.items], [1, 2, 3])
r.check("each event knows its boot", p.events.items[-1]["boot"], "boot-B")

# Button presses settle into one event.
start = p.events.last_seq
p.selected = p.videos.index(SD + "A.mp4")
p.play_selected()
p.step_selection(+1)
p.step_selection(+1)
p.flush_pick()
r.check("presses still settling are not logged yet", p.events.last_seq, start)
p.pending_pick["last"] -= vp.PICK_SETTLE_SEC + 1
p.flush_pick()
r.check("three presses, one event, where it landed", kinds(p)[-1], ("played", "C.mp4"))
r.check("     and only one", p.events.last_seq, start + 1)
p.step_selection(-1)
p.local_stop()
r.check("EXIT logs the pending switch first", kinds(p)[-2:], [("switched", "B.mp4"), ("stopped", "EXIT button")])

# The website's own selections are not logged here: it logs them itself.
before = p.events.last_seq
p.handle_remote(remote("A.mp4", "2026-10-07T13:00:00Z"), None)
r.check("remote selections not logged", p.events.last_seq, before)

# Webcam and USB drives coming and going.
CAM = "/dev/v4l/by-id/usb-Cam-video-index0"
drives = []
vp.mounted_usb_drives = lambda: list(drives)
library = list(LIBRARY)
vp.discover_videos = lambda: list(library)
p.rescan()
library.append(CAM)
p.rescan()
r.check("webcam plugged in", kinds(p)[-1], ("webcam_in", "usb-Cam-video-index0"))
library.remove(CAM)
p.rescan()
r.check("webcam unplugged", kinds(p)[-1], ("webcam_out", ""))
drives.append("STICK")
library += ["/media/pi/STICK/x.mp4", "/media/pi/STICK/y.png"]
p.rescan()
r.check("USB drive plugged in", kinds(p)[-1], ("usb_in", "STICK (2 media files)"))
drives.clear()
p.rescan()
r.check("USB drive removed", kinds(p)[-1], ("usb_out", "STICK"))
before = p.events.last_seq
p.rescan()
r.check("nothing changed, nothing logged", p.events.last_seq, before)
r.check("a fresh player doesn't log what is already there", new_player(LIBRARY + [CAM]).events.last_seq, before)

# A file skipped after three failures.
p.handle_remote(remote("C.mp4", "2026-10-07T14:00:00Z"), None)
for _ in range(vp.MPV_MAX_FAILURES):
    p.mpv_proc.returncode = 2
    p.playing_started = time.monotonic()
    p.handle_mpv_exit()
r.check("unplayable file logged as skipped", kinds(p)[-1], ("skipped", "C.mp4"))

# The log is bounded, survives restarts, and rides along with every report.
for i in range(vp.EVENTS_KEEP + 5):
    p.events.add("played", f"{i}.mp4")
reloaded = vp.EventLog()
r.check("keeps the newest events only", len(reloaded.items), vp.EVENTS_KEEP)
r.check("     reloaded from disk", (reloaded.last_seq, reloaded.log_id), (p.events.last_seq, p.events.log_id))
report = p.status_report()["events"]
r.check("report carries the events", (report["log_id"], len(report["items"]), report["boot"]),
        (p.events.log_id, vp.EVENTS_KEEP, "boot-B"))
sig = p.status_signature()
p.events.add("stopped", "EXIT button")
r.check("a new event triggers a report", p.status_signature() != sig, True)

r.finish("test_scenarios")
