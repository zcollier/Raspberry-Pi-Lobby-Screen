#!/usr/bin/env python3
"""
Unit tests for the pure logic: filename safety, resolution, timestamp handling,
payload validation, and state persistence.

Run with:  python3 tests/test_logic.py
"""
import os
import sys
import json
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import load_player, Results

vp = load_player()
r = Results()

print("=== is_safe_filename ===")
r.check("plain filename", vp.is_safe_filename("spring.mp4"), True)
r.check("dotfile", vp.is_safe_filename(".hidden.mp4"), True)
r.check("path traversal", vp.is_safe_filename("../../etc/passwd"), False)
r.check("absolute path", vp.is_safe_filename("/etc/passwd"), False)
r.check("backslash", vp.is_safe_filename("a\\b.mp4"), False)
r.check("null byte", vp.is_safe_filename("a\x00b.mp4"), False)
r.check("parent dir", vp.is_safe_filename(".."), False)
r.check("empty", vp.is_safe_filename(""), False)
r.check("untrimmed", vp.is_safe_filename(" a.mp4"), False)
r.check("non-string", vp.is_safe_filename(None), False)
r.check("subdirectory", vp.is_safe_filename("sub/a.mp4"), False)

print("\n=== resolve_filename (SD card listed first, so SD wins) ===")
videos = [
    "/home/pi/videos/default.mp4",
    "/home/pi/videos/spring.mp4",
    "/media/pi/STICK/spring.mp4",
    "/media/pi/STICK/Gala.MOV",
]
r.check("exact match prefers SD", vp.resolve_filename("spring.mp4", videos),
        "/home/pi/videos/spring.mp4")
r.check("finds USB-only file", vp.resolve_filename("Gala.MOV", videos),
        "/media/pi/STICK/Gala.MOV")
r.check("case-insensitive fallback", vp.resolve_filename("gala.mov", videos),
        "/media/pi/STICK/Gala.MOV")
r.check("missing file", vp.resolve_filename("nope.mp4", videos), None)
r.check("traversal blocked", vp.resolve_filename("../../etc/passwd", videos), None)

print("\n=== find_default_video (default.mp4 beats default.mov, then first) ===")
r.check("prefers mp4", vp.find_default_video(
    ["/home/pi/videos/default.mov", "/home/pi/videos/default.mp4"]),
    "/home/pi/videos/default.mp4")
r.check("mov when no mp4", vp.find_default_video(
    ["/home/pi/videos/a.mp4", "/home/pi/videos/default.mov"]),
    "/home/pi/videos/default.mov")
r.check("default on USB", vp.find_default_video(["/media/pi/STICK/default.mp4"]),
        "/media/pi/STICK/default.mp4")
r.check("first when no default", vp.find_default_video(["/home/pi/videos/a.mp4"]),
        "/home/pi/videos/a.mp4")
r.check("empty library", vp.find_default_video([]), None)

print("\n=== timestamps: stored in UTC, displayed in America/Chicago ===")
r.check("UTC Z suffix", vp.format_local(vp.parse_iso("2026-08-12T13:00:00Z")),
        "8:00 AM CDT")
r.check("explicit offset", vp.format_local(vp.parse_iso("2026-08-12T08:00:00-05:00")),
        "8:00 AM CDT")
# The reason we never hardcode "CDT": half the year it is CST.
r.check("winter renders CST", vp.format_local(vp.parse_iso("2026-01-12T14:00:00Z")),
        "8:00 AM CST")
r.check("naive assumed local", vp.format_local(vp.parse_iso("2026-08-12T08:05:00")),
        "8:05 AM CDT")
r.check("unparseable", vp.parse_iso("not a date"), None)
r.check("none input", vp.parse_iso(None), None)
r.check("format none", vp.format_local(None), "—")

print("\n=== fingerprints drive change detection ===")
a = {"version": 1, "video": "a.mp4", "updated": "2026-08-12T13:00:00Z"}
b = {"version": 1, "video": "a.mp4", "updated": "2026-08-12T14:00:00Z"}
reordered = {"updated": "2026-08-12T13:00:00Z", "video": "a.mp4", "version": 1}
r.check("key order irrelevant",
        vp.fingerprint_payload(a), vp.fingerprint_payload(reordered))
r.check("bumped timestamp is a new instruction",
        vp.fingerprint_payload(a) != vp.fingerprint_payload(b), True)

print("\n=== parse_remote_payload ===")
now = datetime.now(timezone.utc)
inst = vp.parse_remote_payload(json.dumps(a).encode(), now)
r.check("video field", inst.video, "a.mp4")
r.check("timestamp field", vp.format_local(inst.updated), "8:00 AM CDT")
minimal = vp.parse_remote_payload(b'{"video":"x.mp4"}', now)
r.check("version defaults to 1", minimal.video, "x.mp4")
r.check("updated is optional", minimal.updated, None)

for name, raw in [
    ("malformed JSON",      b"{nope"),
    ("invalid UTF-8",       b"\xff\xfe\x00"),
    ("JSON array",          b"[1,2]"),
    ("missing video",       b'{"version":1}'),
    ("blank video",         b'{"video":"   "}'),
    ("unknown version",     b'{"version":99,"video":"a.mp4"}'),
    ("path traversal",      b'{"video":"../../etc/passwd"}'),
    ("video not a string",  b'{"video":123}'),
]:
    r.expect_raises(name, ValueError, vp.parse_remote_payload, raw, now)

print("\n=== Apache autoindex parsing (fixture captured from the live host) ===")
INDEX_HTML = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">
<html>
 <head><title>Index of /lobby/video</title></head>
 <body>
<h1>Index of /lobby/video</h1>
<pre>      <a href="?C=N;O=D">Name</a>                    <a href="?C=M;O=A">Last modified</a>      <a href="?C=S;O=A">Size</a>  <a href="?C=D;O=A">Description</a><hr>      <a href="/lobby/">Parent Directory</a>                             -
      <a href="default.mov">default.mov</a>          2026-08-12 09:15   12M
      <a href="spring%20musical.mp4">spring musical.mp4</a>   2026-08-12 09:16   48M
      <a href="poster.png">poster.png</a>           2026-08-12 09:17  900K
      <a href="notes.txt">notes.txt</a>            2026-08-12 09:18   1.2K
      <a href="archive/">archive/</a>             2026-08-12 09:19    -
<hr></pre>
</body></html>"""

names = vp.parse_apache_index(INDEX_HTML)
r.check("skips sort links", [n for n in names if n.startswith("?")], [])
r.check("skips parent directory", "/lobby/" in names, False)
r.check("skips subdirectories", "archive/" in names, False)
r.check("URL-decodes spaces", "spring musical.mp4" in names, True)

# list_remote_media() applies the extension filter on top of the raw parse.
media = [n for n in names
         if vp.is_safe_filename(n)
         and os.path.splitext(n)[1].lower() in vp.SUPPORTED_EXTENSIONS]
r.check("keeps videos and images", sorted(media),
        ["default.mov", "poster.png", "spring musical.mp4"])
r.check("drops non-media files", "notes.txt" in media, False)

r.check("empty listing yields nothing", vp.parse_apache_index(
    '<html><body><pre><a href="?C=N;O=D">Name</a>'
    '<a href="/lobby/">Parent Directory</a></pre></body></html>'), [])

print("\n=== image handling ===")
r.check("png is an image", vp.is_image("/home/pi/videos/poster.png"), True)
r.check("JPG uppercase", vp.is_image("/home/pi/videos/A.JPG"), True)
r.check("mov is not", vp.is_image("/home/pi/videos/default.mov"), False)

print("\n=== needs_download: size and timestamp comparison ===")
tmpdir = tempfile.mkdtemp()
sample = os.path.join(tmpdir, "default.mov")
with open(sample, "wb") as f:
    f.write(b"x" * 1000)
mtime = vp.parse_iso("2026-08-12T13:00:00Z")
os.utime(sample, (mtime.timestamp(), mtime.timestamp()))
from pathlib import Path as _P

r.check("missing locally", vp.needs_download(_P(tmpdir) / "nope.mov", 10, mtime)[0], True)
r.check("identical size and time",
        vp.needs_download(_P(sample), 1000, mtime)[0], False)
r.check("different size", vp.needs_download(_P(sample), 2000, mtime)[0], True)
r.check("newer on server", vp.needs_download(
    _P(sample), 1000, vp.parse_iso("2026-08-12T15:00:00Z"))[0], True)
# Difference, not "newer": a rollback on the server should also propagate.
r.check("older on server still syncs", vp.needs_download(
    _P(sample), 1000, vp.parse_iso("2026-08-01T13:00:00Z"))[0], True)
r.check("within timestamp tolerance", vp.needs_download(
    _P(sample), 1000, vp.parse_iso("2026-08-12T13:00:01Z"))[0], False)
r.check("no metadata from server", vp.needs_download(_P(sample), None, None)[0], False)

print("\n=== state persistence ===")
tmp = tempfile.mkdtemp()
vp.STATE_FILE = os.path.join(tmp, "state.json")
vp.LEGACY_STATE_FILE = os.path.join(tmp, "last_played.txt")

saved = vp.Player(None, None, None, None)
saved.target_name = "a.mp4"
saved.target_path = "/home/pi/videos/a.mp4"
saved.target_source = vp.Source.REMOTE
saved.target_set_at = vp.parse_iso("2026-08-12T13:00:00Z")
saved.last_seen_remote = "abc123"
saved.remote_video = "a.mp4"
saved.remote_updated = vp.parse_iso("2026-08-12T13:00:00Z")
saved.save_state()

loaded = vp.Player(None, None, None, None)
loaded.load_state()
r.check("target survives restart", loaded.target_name, "a.mp4")
r.check("source survives restart", loaded.target_source, vp.Source.REMOTE)
# Without this, a reboot would re-apply the last remote instruction and
# clobber a local override made after it.
r.check("fingerprint survives restart", loaded.last_seen_remote, "abc123")
r.check("timestamp survives restart",
        vp.format_local(loaded.target_set_at), "8:00 AM CDT")

os.remove(vp.STATE_FILE)
with open(vp.LEGACY_STATE_FILE, "w") as f:
    f.write("/home/pi/videos/old.mp4\n")
migrated = vp.Player(None, None, None, None)
migrated.load_state()
r.check("legacy filename", migrated.target_name, "old.mp4")
r.check("legacy path", migrated.target_path, "/home/pi/videos/old.mp4")
r.check("legacy file upgraded", os.path.exists(vp.STATE_FILE), True)

r.finish("test_logic")
