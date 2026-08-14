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

print("\n=== Scenario 13: sync errors are surfaced but harmless ===")
fresh_state()
p = new_player()
p.handle_remote(remote("A.mp4", "2026-08-12T13:00:00Z"), None)
before = playing(p)
p.handle_sync({"downloaded": [], "removed": [], "errors": ["boom"], "checked": 0})
r.check("playback unaffected", playing(p), before)
r.check("error kept for display", p.sync_error, "boom")

r.finish("test_scenarios")
