#!/usr/bin/env python3
import argparse
import sys
import time
import traceback
import os
import json
import hashlib
import shutil
import signal

import pigpio
from nrf24 import *

# ----------------------------------------------------------
# QUICK MODE RECEIVER (Buffer-first version)
# ----------------------------------------------------------
# - Always writes received files first to a local buffer (~/.nrf24_received_buffer)
# - Periodically checks for USB mounts (/dev/sd*)
# - Moves buffered files automatically to the first available USB mount
# - Avoids overwriting existing files
# - This script does NOT accept or use an output path argument
# ----------------------------------------------------------

BUFFER_DIR = os.path.expanduser("~/.nrf24_received_buffer")
POLL_MOUNT_INTERVAL = 2.0  # seconds between USB mount checks


def list_usb_mounts():
    """Return a list of mount points for devices like /dev/sd*."""
    mounts = []
    try:
        with open("/proc/mounts", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    device = parts[0]
                    mountpoint = parts[1]
                    if device.startswith("/dev/sd"):
                        mounts.append(mountpoint)
    except Exception as e:
        print(f"[MOUNTS] Warning: cannot read /proc/mounts: {e}")
    return sorted(set(mounts))


def ensure_buffer_dir():
    """Ensure the local buffer directory exists."""
    try:
        os.makedirs(BUFFER_DIR, exist_ok=True)
    except Exception as e:
        print(f"[BUFFER] Failed to create {BUFFER_DIR}: {e}")
        raise


def move_buffered_files_to_mounts():
    """
    Move all files from the buffer to the first available USB mount.
    Avoid overwriting by appending _1, _2, etc.
    """
    mounts = list_usb_mounts()
    if not mounts:
        return False

    try:
        files = [f for f in os.listdir(BUFFER_DIR) if os.path.isfile(os.path.join(BUFFER_DIR, f))]
    except FileNotFoundError:
        return False
    except Exception as e:
        print(f"[BUFFER] Error listing buffer dir: {e}")
        return False

    if not files:
        return False

    target_mount = mounts[0]
    moved_any = False
    for fname in files:
        src = os.path.join(BUFFER_DIR, fname)
        dest = os.path.join(target_mount, fname)
        base, ext = os.path.splitext(fname)
        c = 1
        while os.path.exists(dest):
            dest = os.path.join(target_mount, f"{base}_{c}{ext}")
            c += 1
        try:
            shutil.move(src, dest)
            print(f"[BUFFER] Moved '{fname}' -> '{dest}'")
            moved_any = True
        except Exception as e:
            print(f"[BUFFER] Failed to move '{fname}' -> '{dest}': {e}")
    return moved_any


# Graceful shutdown flag
should_exit = False


def sigint_handler(signum, frame):
    global should_exit
    should_exit = True
    print("\n[MAIN] Interrupt received, exiting after current operation...")


signal.signal(signal.SIGINT, sigint_handler)
signal.signal(signal.SIGTERM, sigint_handler)


if __name__ == "__main__":
    print("Quick Mode Test - File Receiver (buffer-first).")

    parser = argparse.ArgumentParser(
        prog="receiver-file-buffered.py",
        description="NRF24 File Receiver - always buffer first (no output path)."
    )
    parser.add_argument('-n', '--hostname', type=str, default='localhost', help="Hostname for the pigpio daemon.")
    parser.add_argument('-p', '--port', type=int, default=8888, help="Port number of the pigpio daemon.")
    parser.add_argument('address', type=str, nargs='?', default='FILEX', help="Address to listen to (5 ASCII characters).")
    # NOTE: intentionally no positional arg for output path
    args = parser.parse_args()
    hostname = args.hostname
    port = args.port
    address = args.address

    # Connect to pigpiod
    print(f'Connecting to GPIO daemon on {hostname}:{port} ...')
    pi = pigpio.pi(hostname, port)
    if not pi.connected:
        print("Could not connect to Raspberry Pi. Exiting.")
        sys.exit(1)

    # NRF24 setup (unchanged)
    nrf = NRF24(pi, ce=25, payload_size=32, channel=100,
               data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN)
    nrf.set_address_bytes(len(address))
    nrf.open_reading_pipe(RF24_RX_ADDR.P1, address)
    nrf.show_registers()

    try:
        print(f"Listening on address: {address}")
        ensure_buffer_dir()
        print("[INFO] Buffer-first mode enabled: received files are written to the local buffer and moved to USB when available.")
        last_mounts_poll = 0.0

        while not should_exit:
            buf = b''

            # Transmission state variables (unchanged)
            stage = 'header_len'
            header_len = None
            header_bytes_needed = None
            header_obj = None
            file_bytes_remaining = None
            outfile = None
            hasher = None
            received_bytes_total = 0
            buffer_target_path = None

            print("Waiting for incoming data... (press Ctrl-C to cancel)")

            while not should_exit:
                # Periodically check for new USB mounts
                now = time.time()
                if now - last_mounts_poll > POLL_MOUNT_INTERVAL:
                    moved = move_buffered_files_to_mounts()
                    if moved:
                        print("[BUFFER] Buffered files moved to USB.")
                    last_mounts_poll = now

                # Wait for NRF24 data
                if not nrf.data_ready():
                    time.sleep(0.01)
                    continue

                payload = nrf.get_payload()
                if payload is None:
                    continue

                buf += payload

                while True:
                    if stage == 'header_len':
                        if len(buf) < 4:
                            break
                        header_len = int.from_bytes(buf[:4], byteorder='big')
                        buf = buf[4:]
                        header_bytes_needed = header_len
                        stage = 'header'
                        print(f"[PROTO] Header length: {header_len} bytes")

                    elif stage == 'header':
                        if len(buf) < header_bytes_needed:
                            break
                        header_bytes = buf[:header_bytes_needed]
                        buf = buf[header_bytes_needed:]
                        try:
                            header_obj = json.loads(header_bytes.decode('utf-8'))
                        except Exception as e:
                            raise RuntimeError(f"Failed to parse header JSON: {e}")
                        filename = header_obj.get('filename') or 'received.bin'
                        filesize = int(header_obj.get('filesize', 0))
                        print(f"[PROTO] Header parsed. filename='{filename}', filesize={filesize} bytes")

                        # --- always write to buffer first ---
                        ensure_buffer_dir()
                        dest = os.path.join(BUFFER_DIR, filename)
                        base, ext = os.path.splitext(filename)
                        c = 1
                        while os.path.exists(dest):
                            dest = os.path.join(BUFFER_DIR, f"{base}_{c}{ext}")
                            c += 1
                        buffer_target_path = dest
                        try:
                            outfile = open(buffer_target_path, 'wb')
                        except Exception as e:
                            raise RuntimeError(f"Failed to open buffer file for writing: {e}")
                        print(f"[WRITE] Writing first to buffer: {buffer_target_path}")
                        hasher = hashlib.md5()
                        file_bytes_remaining = filesize
                        received_bytes_total = 0
                        stage = 'file'

                    elif stage == 'file':
                        if file_bytes_remaining is None:
                            raise RuntimeError("file_bytes_remaining is None in 'file' stage.")
                        if file_bytes_remaining == 0:
                            stage = 'md5'
                            continue
                        if len(buf) == 0:
                            break
                        take = min(len(buf), file_bytes_remaining)
                        chunk = buf[:take]
                        buf = buf[take:]
                        outfile.write(chunk)
                        hasher.update(chunk)
                        received_bytes_total += len(chunk)
                        file_bytes_remaining -= len(chunk)
                        print(f"[PROG] Received {received_bytes_total} / {received_bytes_total + file_bytes_remaining} bytes...", end='\r')
                        if file_bytes_remaining == 0:
                            print(f"\n[PROG] Finished receiving file data ({received_bytes_total} bytes). Waiting for MD5 footer...")
                            stage = 'md5'
                            continue

                    elif stage == 'md5':
                        if len(buf) < 33:
                            break
                        marker = buf[0:1]
                        if marker != b'M':
                            raise RuntimeError(f"Unexpected MD5 marker byte: {marker!r}. Expected b'M'.")
                        md5_hex_received = buf[1:33].decode('ascii', errors='ignore')
                        buf = buf[33:]
                        outfile.flush()
                        outfile.close()
                        outfile = None
                        md5_local = hasher.hexdigest()
                        print(f"[MD5] received: {md5_hex_received}")
                        print(f"[MD5] local   : {md5_local}")
                        if md5_local == md5_hex_received:
                            print(f"[RESULT] SUCCESS: MD5 matches. File buffered at: {buffer_target_path}")
                        else:
                            print(f"[RESULT] ERROR: MD5 mismatch! File may be corrupted. Buffered at: {buffer_target_path}")
                        stage = 'done'
                        break

                    elif stage == 'done':
                        break

                    else:
                        raise RuntimeError(f"Unknown stage: {stage}")

                if stage == 'done':
                    break

            # After each transfer, try to move buffered files if a USB is connected
            try:
                moved = move_buffered_files_to_mounts()
                if moved:
                    print("[BUFFER] Buffered files moved after transfer.")
            except Exception as e:
                print(f"[BUFFER] Error while moving buffered files: {e}")

            if should_exit:
                break

            time.sleep(0.1)

        print("[MAIN] Exiting receiver loop.")

    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception:
        traceback.print_exc()
    finally:
        try:
            if 'outfile' in locals() and outfile and not outfile.closed:
                outfile.close()
        except Exception:
            pass
        try:
            nrf.power_down()
            pi.stop()
        except Exception:
            pass


