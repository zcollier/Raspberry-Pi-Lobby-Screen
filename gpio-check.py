#!/usr/bin/env python3
"""
GPIO button diagnostic for the VRHS lobby screen.

Reads the four button pins directly by polling, rather than using the edge
detection the player relies on. That distinction is the point: it separates a
wiring fault from a software one.

  Presses show up here but the buttons don't work in the player
      -> wiring is fine; edge detection (add_event_detect) is failing.
         Usually RPi.GPIO on a newer Raspberry Pi OS kernel.

  Presses do NOT show up here
      -> wiring, a dead button, or a bad ground connection.

Stop the player first so two processes aren't configuring the same pins:

    sudo systemctl stop video-player
    python3 gpio-check.py
    sudo systemctl start video-player
"""

import sys
import time

PINS = {
    17: "EXIT",
    27: "PREV",
    22: "NEXT",
    23: "PLAY",
}

try:
    import RPi.GPIO as GPIO
except ImportError as exc:
    print(f"RPi.GPIO is not installed: {exc}")
    print("Install it with:  sudo apt-get install -y python3-rpi.gpio")
    sys.exit(1)

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

for pin in PINS:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

print("Pins configured with internal pull-ups.")
print("A wired, unpressed button reads 1. Pressing it should read 0.\n")

levels = {pin: GPIO.input(pin) for pin in PINS}
for pin, name in PINS.items():
    state = "1 (idle)" if levels[pin] else "0 (PRESSED, or shorted to ground)"
    print(f"  BCM {pin:<3} {name:<5} = {state}")

print("\nNow press each button in turn. Ctrl-C to finish.\n")

# Also verify that edge detection — what the player actually uses — can even be
# registered on this kernel. This is the call that fails on newer Raspberry Pi
# OS releases, and the failure is exactly what takes the buttons out.
edge_ok = True
for pin in PINS:
    try:
        GPIO.add_event_detect(pin, GPIO.FALLING, bouncetime=300)
    except RuntimeError as exc:
        edge_ok = False
        print(f"  edge detection FAILED on BCM {pin}: {exc}")

if edge_ok:
    print("  edge detection registered on all four pins.\n")
else:
    print("\n  ^ This is why the player's buttons stopped working.")
    print("    Polling below still works, so your wiring is probably fine.\n")

seen = set()
try:
    while True:
        for pin, name in PINS.items():
            level = GPIO.input(pin)
            if level != levels[pin]:
                levels[pin] = level
                if level == 0:
                    seen.add(name)
                    print(f"  {name} (BCM {pin}) pressed"
                          f"   [seen so far: {', '.join(sorted(seen))}]")
        time.sleep(0.02)
except KeyboardInterrupt:
    missing = [n for n in PINS.values() if n not in seen]
    print("\n\nSummary")
    print(f"  Responded  : {', '.join(sorted(seen)) or 'none'}")
    print(f"  No response: {', '.join(missing) or 'none'}")
    if missing and seen:
        print("\n  Some buttons work, so the Pi and its ground are fine.")
        print("  Check the wiring on the ones that didn't respond.")
    elif not seen:
        print("\n  Nothing responded. Check the shared ground wire first —")
        print("  one loose ground takes out every button at once.")
    GPIO.cleanup()
