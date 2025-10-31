#!/usr/bin/env python3
"""
Mid Range Mode Test Wrapper
- Ensures 'pigpiod' is running (starts it with sudo if needed).
- Launches either the sender or the receiver script automatically.
Usage:
  python3 mid-range-mode-test-auto.py sender
  python3 mid-range-mode-test-auto.py receiver
"""

import sys
import subprocess
import os
import time

SELF_DIR = os.path.dirname(os.path.abspath(__file__))

def which(script_name):
    candidate = os.path.join(SELF_DIR, script_name)
    if os.path.exists(candidate):
        return candidate
    return None

def pigpiod_is_running():
    """Check if pigpiod is active."""
    try:
        subprocess.check_output(["pgrep", "-x", "pigpiod"])
        return True
    except subprocess.CalledProcessError:
        return False

def ensure_pigpiod_running():
    """Start pigpiod if it's not running."""
    if pigpiod_is_running():
        print("✅ pigpiod is already running.")
        return
    print("⚙️  pigpiod is not running. Starting it with sudo...")
    try:
        subprocess.run(["sudo", "pigpiod"], check=True)
        time.sleep(1.0)
        if pigpiod_is_running():
            print("✅ pigpiod started successfully.")
        else:
            print("⚠️ pigpiod launch could not be verified.")
    except Exception as e:
        print(f"❌ Failed to start pigpiod: {e}")
        sys.exit(1)

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ('sender', 'receiver'):
        print("Usage: mid-range-mode-test.py [sender|receiver] [args...]")
        sys.exit(1)

    mode = sys.argv[1]
    args = sys.argv[2:]

    ensure_pigpiod_running()

    if mode == 'sender':
        target = which('mid-range-mode-sender-auto.py')
    else:
        target = which('mid-range-mode-receiver-auto.py')

    if not target:
        print(f"❌ Could not find the target script for {mode}.")
        sys.exit(1)

    cmd = [sys.executable, target] + args
    print("🚀 Running:", " ".join(cmd))
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user.")
    except Exception as e:
        print(f"❌ Error while running: {e}")

if __name__ == "__main__":
    main()
