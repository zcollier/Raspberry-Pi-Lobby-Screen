#!/usr/bin/env python3
"""
End-to-end media sync tests against a real local HTTP server.

Exercises the actual download path — directory listing, HEAD metadata, chunked
download, size verification, timestamp preservation, and the atomic rename —
rather than mocking it out.

Run with:  python3 tests/test_sync.py
"""
import os
import sys
import time
import shutil
import logging
import tempfile
import functools
import threading
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import load_player, Results

vp = load_player()
r = Results()
logging.disable(logging.INFO)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


# --- a throwaway web server standing in for the Boosters site ---------------
served = tempfile.mkdtemp()
local = tempfile.mkdtemp()

handler = functools.partial(QuietHandler, directory=served)
httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()

vp.REMOTE_MEDIA_DIR_URL = f"http://127.0.0.1:{port}/"


def publish(name, content, mtime_iso=None):
    """Write a file to the fake web server, optionally with a set mtime."""
    path = Path(served) / name
    path.write_bytes(content)
    if mtime_iso:
        stamp = vp.parse_iso(mtime_iso).timestamp()
        os.utime(path, (stamp, stamp))
    return path


def local_names():
    return sorted(p.name for p in Path(local).iterdir())


try:
    print("=== initial sync downloads media, ignores everything else ===")
    publish("default.mov", b"A" * 5000, "2026-08-12T13:00:00Z")
    publish("poster.png", b"B" * 3000, "2026-08-12T13:05:00Z")
    publish("notes.txt", b"not media", "2026-08-12T13:06:00Z")

    result = vp.sync_once(local)
    r.check("no errors", result["errors"], [])
    r.check("downloaded both media files",
            sorted(result["downloaded"]), ["default.mov", "poster.png"])
    r.check("landed on disk", local_names(), ["default.mov", "poster.png"])
    r.check("skipped non-media", "notes.txt" in local_names(), False)
    r.check("content is intact",
            (Path(local) / "default.mov").read_bytes(), b"A" * 5000)

    print("\n=== timestamps are preserved, so comparisons are stable ===")
    remote_mtime = (Path(served) / "default.mov").stat().st_mtime
    local_mtime = (Path(local) / "default.mov").stat().st_mtime
    r.check("mtime copied from server", abs(remote_mtime - local_mtime) < 2, True)

    print("\n=== a second pass downloads nothing ===")
    result = vp.sync_once(local)
    r.check("nothing re-downloaded", result["downloaded"], [])
    r.check("still checked both", result["checked"], 2)

    print("\n=== replacing a file with a different size re-downloads it ===")
    publish("default.mov", b"C" * 9000, "2026-08-12T14:00:00Z")
    result = vp.sync_once(local)
    r.check("re-downloaded the changed file", result["downloaded"], ["default.mov"])
    r.check("new content on disk",
            (Path(local) / "default.mov").read_bytes(), b"C" * 9000)
    r.check("untouched file left alone",
            (Path(local) / "poster.png").read_bytes(), b"B" * 3000)

    print("\n=== same size but a new timestamp also re-downloads ===")
    publish("default.mov", b"D" * 9000, "2026-08-12T16:00:00Z")
    result = vp.sync_once(local)
    r.check("timestamp change is enough", result["downloaded"], ["default.mov"])
    r.check("content replaced",
            (Path(local) / "default.mov").read_bytes(), b"D" * 9000)

    print("\n=== a new file appearing on the server is picked up ===")
    publish("gala.mp4", b"E" * 2000, "2026-08-12T17:00:00Z")
    result = vp.sync_once(local)
    r.check("only the new file", result["downloaded"], ["gala.mp4"])
    r.check("all three present", local_names(),
            ["default.mov", "gala.mp4", "poster.png"])

    print("\n=== files removed from the server are kept by default ===")
    (Path(served) / "gala.mp4").unlink()
    result = vp.sync_once(local)
    r.check("nothing removed locally", result["removed"], [])
    r.check("local copy survives", "gala.mp4" in local_names(), True)

    print("\n=== an incomplete download never replaces a good file ===")
    good = (Path(local) / "poster.png").read_bytes()
    real_meta = vp.remote_file_meta
    vp.remote_file_meta = lambda name: (999999, real_meta(name)[1])  # lie about size
    result = vp.sync_once(local)
    r.check("reported an error", len(result["errors"]) > 0, True)
    r.check("nothing claimed as downloaded", result["downloaded"], [])
    r.check("existing file untouched",
            (Path(local) / "poster.png").read_bytes(), good)
    r.check("no .part left behind",
            [n for n in os.listdir(local) if n.endswith(".part")], [])
    vp.remote_file_meta = real_meta

    print("\n=== a full disk is refused rather than half-written ===")
    publish("big.mp4", b"F" * 4000, "2026-08-12T18:00:00Z")
    real_usage = vp.shutil.disk_usage
    vp.shutil.disk_usage = lambda p: shutil._ntuple_diskusage(100, 100, 1000)
    result = vp.sync_once(local)
    vp.shutil.disk_usage = real_usage
    r.check("refused the download", "big.mp4" in local_names(), False)
    r.check("explained why", any("free space" in e for e in result["errors"]), True)

    print("\n=== an unreachable server changes nothing ===")
    before = local_names()
    saved_url = vp.REMOTE_MEDIA_DIR_URL
    vp.REMOTE_MEDIA_DIR_URL = "http://127.0.0.1:1/"     # nothing listening
    result = vp.sync_once(local)
    vp.REMOTE_MEDIA_DIR_URL = saved_url
    r.check("reported the failure", len(result["errors"]) > 0, True)
    r.check("local files untouched", local_names(), before)

    print("\n=== a missing local directory is reported, not created ===")
    result = vp.sync_once(os.path.join(local, "does-not-exist"))
    r.check("refused to run", len(result["errors"]) > 0, True)
    r.check("downloaded nothing", result["downloaded"], [])

finally:
    httpd.shutdown()
    httpd.server_close()

r.finish("test_sync")
