"""
Shared bootstrap for the test suites.

Loads video-player.py with pygame stubbed out, so the logic can be tested on any
machine — no display, no GPIO, no pygame install required.
"""
import sys
import types
import importlib.util
from pathlib import Path

PLAYER_PATH = Path(__file__).resolve().parent.parent / "video-player.py"


def load_player():
    """Import video-player.py as a module named 'vp'."""
    if "pygame" not in sys.modules:
        pg = types.ModuleType("pygame")
        pg.USEREVENT = 32850
        pg.error = RuntimeError
        pg.event = types.SimpleNamespace(
            post=lambda e: None,
            Event=lambda t, d=None: (t, d),
        )
        pg.Surface = type("Surface", (), {})
        pg.Rect = type("Rect", (), {})
        sys.modules["pygame"] = pg

    spec = importlib.util.spec_from_file_location("vp", PLAYER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Results:
    """Minimal assertion tracker — avoids a pytest dependency on the Pi."""

    def __init__(self):
        self.failures = []

    def check(self, name, got, want):
        ok = got == want
        if not ok:
            self.failures.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  {'ok  ' if ok else 'FAIL'} {name}"
              + ("" if ok else f"   (got {got!r}, want {want!r})"))

    def expect_raises(self, name, exc_type, fn, *args):
        try:
            fn(*args)
        except exc_type as exc:
            print(f"  ok   {name}  ({exc})")
            return
        self.failures.append(f"{name}: should have raised {exc_type.__name__}")
        print(f"  FAIL {name}: no exception raised")

    def finish(self, label):
        print("\n" + "=" * 55)
        if self.failures:
            print(f"{label}: {len(self.failures)} FAILURE(S)")
            for f in self.failures:
                print("  " + f)
            sys.exit(1)
        print(f"{label}: ALL PASS")
