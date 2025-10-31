#!/usr/bin/env python3
"""
Quick Mode Sender — robust chunked transfer with per-chunk zstd compression,
ACKs, streaming and unlimited retries.

Requires: pip3 install zstandard
"""

import argparse
import os
import sys
import time
import math
import json
import hashlib
import zstandard as zstd
import traceback

import pigpio
from nrf24 import *

# Transport parameters
CHUNK_SIZE = 32        # radio payload size
CHUNK_RAW  = 4096      # raw bytes per logical chunk
ZSTD_LEVEL = 3
HEADER_TERMINATOR = b'\n\n'
MAX_BACKOFF = 60.0

# Utility functions
def md5_bytes(b: bytes) -> str:
    h = hashlib.md5(); h.update(b); return h.hexdigest()

def send_raw_bytes(nrf, buf: bytes):
    for i in range(0, len(buf), CHUNK_SIZE):
        chunk = buf[i:i+CHUNK_SIZE]
        nrf.send(chunk)
        nrf.wait_until_sent()

def recv_messages_poll(nrf, timeout=0.1):
    """Poll inbound messages for `timeout` seconds. Return list of raw payload chunks."""
    end = time.time() + timeout
    out = []
    while time.time() < end:
        if nrf.data_ready():
            out.append(nrf.get_payload())
        else:
            time.sleep(0.001)
    return out

def parse_json_messages_from_bytesbuf(buf: bytearray):
    """Extract all JSON headers (terminated by HEADER_TERMINATOR) from buf.
       Returns list of parsed JSON objects and the remaining buffer (bytearray)."""
    msgs = []
    while True:
        idx = buf.find(HEADER_TERMINATOR)
        if idx == -1:
            break
        header = bytes(buf[:idx])
        try:
            obj = json.loads(header.decode('utf-8'))
            msgs.append(obj)
        except Exception:
            # If parse fails, skip this header chunk
            pass
        del buf[:idx + len(HEADER_TERMINATOR)]
    return msgs, buf

def wait_for_ack_for_index(nrf, idx, timeout):
    """Poll inbound messages until timeout. Return True if receives ack containing idx."""
    buf = bytearray()
    end = time.time() + timeout
    while time.time() < end:
        if nrf.data_ready():
            payload = nrf.get_payload()
            buf.extend(payload)
            msgs, buf = parse_json_messages_from_bytesbuf(buf)
            for m in msgs:
                if m.get('type') == 'ack':
                    rec = m.get('received', [])
                    if idx in rec or any(int(r)==idx for r in rec):
                        return True
        else:
            time.sleep(0.001)
    return False

# Main streaming sender with unlimited retries (per-chunk)
def send_file_streaming_with_retries(pi, nrf, filepath, address):
    filename = os.path.basename(filepath)
    orig_size = os.path.getsize(filepath)
    total_chunks = math.ceil(orig_size / CHUNK_RAW)

    # compute file md5 (optional but helpful)
    file_md5 = hashlib.md5()
    with open(filepath, 'rb') as f:
        while True:
            b = f.read(65536)
            if not b: break
            file_md5.update(b)
    file_md5_hex = file_md5.hexdigest()

    # Send file-level header
    file_header = {
        'type': 'file',
        'filename': filename,
        'orig_size': orig_size,
        'file_md5': file_md5_hex,
        'total_chunks': total_chunks,
        'chunk_raw_size': CHUNK_RAW,
        'compression': 'zstd',
        'compression_level': ZSTD_LEVEL
    }
    send_raw_bytes(nrf, json.dumps(file_header).encode('utf-8') + HEADER_TERMINATOR)
    print(f"Sent file header: {filename}, size={orig_size}, chunks={total_chunks}")

    compressor = zstd.ZstdCompressor(level=ZSTD_LEVEL)

    # Open file and stream chunk-by-chunk (no full precompress)
    with open(filepath, 'rb') as f:
        for idx in range(total_chunks):
            part = f.read(CHUNK_RAW)
            orig_chunk_size = len(part)
            chunk_md5 = md5_bytes(part)
            comp = compressor.compress(part)
            comp_size = len(comp)

            chunk_header = {
                'type': 'chunk',
                'idx': idx,
                'comp_size': comp_size,
                'orig_size': orig_chunk_size,
                'chunk_md5': chunk_md5
            }
            header_bytes = json.dumps(chunk_header).encode('utf-8') + HEADER_TERMINATOR

            backoff = 1.0
            while True:
                try:
                    send_raw_bytes(nrf, header_bytes)
                    send_raw_bytes(nrf, comp)
                except Exception as e:
                    print(f"Send low-level error sending chunk {idx}: {e}")
                    traceback.print_exc()

                # wait for ack for this idx
                ack_ok = wait_for_ack_for_index(nrf, idx, timeout=backoff+0.2)
                if ack_ok:
                    print(f"Chunk {idx}/{total_chunks-1} ACKed")
                    break
                else:
                    print(f"No ACK for chunk {idx}. Backoff {backoff}s and retrying (unlimited retries).")
                    time.sleep(backoff)
                    backoff = min(MAX_BACKOFF, backoff * 2)

    # send end header
    end_header = {'type':'end','filename':filename}
    send_raw_bytes(nrf, json.dumps(end_header).encode('utf-8') + HEADER_TERMINATOR)
    print("File transfer finished (sender).")

def main():
    parser = argparse.ArgumentParser(description="Robust NRF24 Sender (chunked zstd with ACKs)")
    parser.add_argument('filepath', help="Path to file to send (.txt etc.)")
    parser.add_argument('-n','--hostname', default='localhost')
    parser.add_argument('-p','--port', type=int, default=8888)
    parser.add_argument('address', nargs='?', default='FILEX', help="5-char NRF24 address")
    args = parser.parse_args()

    if not os.path.exists(args.filepath):
        print("File not found:", args.filepath); sys.exit(1)

    print(f"Connecting to pigpio at {args.hostname}:{args.port} ...")
    pi = pigpio.pi(args.hostname, args.port)
    if not pi.connected:
        print("Could not connect to pigpio daemon."); sys.exit(1)

    nrf = NRF24(pi, ce=25, payload_size=CHUNK_SIZE, channel=100,
                data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN)
    # open both pipes (we need bidirectional comms for ACKs)
    nrf.set_address_bytes(len(args.address))
    nrf.open_writing_pipe(args.address)
    nrf.open_reading_pipe(RF24_RX_ADDR.P1, args.address)
    nrf.set_retransmission(15, 15)
    nrf.show_registers()

    try:
        send_file_streaming_with_retries(pi, nrf, args.filepath, args.address)
    except KeyboardInterrupt:
        print("User interrupted.")
    finally:
        nrf.power_down()
        pi.stop()

if __name__ == "__main__":
    main()
