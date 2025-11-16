#!/usr/bin/env python3
"""
Quick Mode Auto Sender (MD5 + size-based completion) with Zstd compression (level 3)
Requires: pip3 install zstandard
"""

import argparse
import sys
import time
import json
import os
import hashlib
import traceback

import pigpio
from nrf24 import *

HEADER_TERMINATOR = b'\n\n'
CHUNK_SIZE = 32
POLL_INTERVAL = 1.0  # seconds
ZSTD_LEVEL = 3

def find_usb_mounts():
    mounts = []
    try:
        with open('/proc/mounts', 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    mount_point = parts[1]
                    if mount_point.startswith('/media/') or mount_point.startswith('/mnt/'):
                        mounts.append(mount_point)
    except Exception:
        pass
    return mounts

def find_most_recent_txt(mount_point):
    txt_files = []
    for root, _, files in os.walk(mount_point):
        for fn in files:
            if fn.lower().endswith('.txt'):
                full = os.path.join(root, fn)
                try:
                    mtime = os.path.getmtime(full)
                    txt_files.append((mtime, full))
                except Exception:
                    pass
    if not txt_files:
        return None
    txt_files.sort(reverse=True)
    return txt_files[0][1]

def wait_for_usb_and_get_txt(poll_interval=POLL_INTERVAL):
    print("Waiting for a USB drive containing a .txt file...")
    while True:
        mounts = find_usb_mounts()
        if mounts:
            for m in mounts:
                candidate = find_most_recent_txt(m)
                if candidate:
                    print(f"Found .txt on {m}: {candidate}")
                    return candidate, m
        time.sleep(poll_interval)

def wait_for_unplug(mount_point, poll_interval=POLL_INTERVAL):
    print(f"Waiting for {mount_point} to be removed to reset...")
    while True:
        mounts = find_usb_mounts()
        if mount_point not in mounts:
            print(f"{mount_point} removed.")
            return
        time.sleep(poll_interval)

def compute_md5(bytes_data):
    h = hashlib.md5()
    h.update(bytes_data)
    return h.hexdigest()

# Compress using python zstandard only
def compress_zstd(data_bytes, level=ZSTD_LEVEL):
    try:
        import zstandard as zstd
    except Exception as e:
        raise RuntimeError("The “zstandard” library is not installed. Install it with: pip3 install zstandard") from e
    cctx = zstd.ZstdCompressor(level=level)
    return cctx.compress(data_bytes)

def send_file(pi, nrf, filepath, address):
    print(f"Reading file: {filepath}")
    with open(filepath, 'rb') as f:
        data = f.read()

    orig_size = len(data)
    orig_md5 = compute_md5(data)
    filename = os.path.basename(filepath)

    compressed = compress_zstd(data, level=ZSTD_LEVEL)
    compressed_size = len(compressed)
    compression_used = "zstd"

    header_obj = {
        'filename': filename,
        'size': compressed_size,        # size of bytes that will be sent (compressed size)
        'md5': orig_md5,                # MD5 of original (so receiver can verify after decompression)
        'orig_size': orig_size,
        'compression': compression_used,
        'compression_level': ZSTD_LEVEL
    }

    header = json.dumps(header_obj).encode('utf-8') + HEADER_TERMINATOR

    print(f"Header: {header_obj}")

    print("Sending header + file (compressed bytes)...")
    sent_bytes = 0  # count of FILE bytes sent (not counting header)
    header_pos = 0  # cursor within header bytes
    data_pos = 0    # cursor within file data

    # Send full CHUNK_SIZE header chunks first.
    while header_pos + CHUNK_SIZE <= len(header):
        chunk = header[header_pos:header_pos + CHUNK_SIZE]
        nrf.send(chunk)
        nrf.wait_until_sent()
        header_pos += CHUNK_SIZE

    # Handle remaining (partial) header chunk by filling with the first file bytes.
    if header_pos < len(header):
        remaining_header = header[header_pos:]
        need = CHUNK_SIZE - len(remaining_header)

        # Take 'need' bytes from the beginning of compressed data (if available)
        fill = compressed[:need]
        chunk = remaining_header + fill
        nrf.send(chunk)
        nrf.wait_until_sent()

        # Advance data_pos for the bytes we've consumed to fill the header tail
        data_pos += len(fill)
        sent_bytes += len(fill)  # we already sent these file bytes

    # Now send the remaining compressed data in CHUNK_SIZE blocks starting from data_pos
    for i in range(data_pos, compressed_size, CHUNK_SIZE):
        chunk = compressed[i:i + CHUNK_SIZE]
        nrf.send(chunk)
        try:
            nrf.wait_until_sent()
            sent_bytes += len(chunk)
            progress = (sent_bytes / max(1, compressed_size)) * 100
            print(f"Progress: {progress:.1f}% ({sent_bytes}/{compressed_size})", end='\r')
        except TimeoutError:
            print("\nTimeout on chunk send. Aborting this transfer.")
            raise

    print("\nTransfer complete.")

def main():
    parser = argparse.ArgumentParser(description="NRF24 Auto File Sender (MD5) with zstd compression")
    parser.add_argument('-n', '--hostname', default='localhost', help="Hostname for pigpio daemon")
    parser.add_argument('-p', '--port', type=int, default=8888, help="Port for pigpio daemon")
    parser.add_argument('address', nargs='?', default='FILEX', help="5-char NRF24 address")
    args = parser.parse_args()

    print(f"Connecting to pigpio daemon on {args.hostname}:{args.port} ...")
    pi = pigpio.pi(args.hostname, args.port)
    if not pi.connected:
        print("Could not connect to pigpio daemon. Exiting.")
        sys.exit(1)

    nrf = NRF24(pi, ce=25, payload_size=CHUNK_SIZE, channel=100,
                data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN)
    nrf.set_address_bytes(len(args.address))
    nrf.set_retransmission(15, 15)
    nrf.open_writing_pipe(args.address)
    nrf.show_registers()

    try:
        # Main loop: espera USB -> envia -> espera unplug -> repeteix
        while True:
            try:
                txt_path, mount_point = wait_for_usb_and_get_txt()
                try:
                    send_file(pi, nrf, txt_path, args.address)
                except Exception:
                    traceback.print_exc()
                    print("Error during transmission. Will wait for next removal/insert.")
                # After a send (successful or not), wait until the USB is removed to "reset"
                wait_for_unplug(mount_point)
            except KeyboardInterrupt:
                print("\nUser interrupted. Exiting loop.")
                break
    finally:
        nrf.power_down()
        pi.stop()

if __name__ == '__main__':
    main()
