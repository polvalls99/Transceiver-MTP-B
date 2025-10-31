#!/usr/bin/env python3
"""
Quick Mode Receiver — robust chunked receiver with per-chunk zstd decompression,
persistent .partial + .meta.json state and periodic ACKs back to sender.

Requires: pip3 install zstandard
"""

import argparse
import os
import sys
import time
import json
import zstandard as zstd
import hashlib
import shutil
import traceback

import pigpio
from nrf24 import *

# Transport parameters
CHUNK_SIZE = 32
HEADER_TERMINATOR = b'\n\n'
ACK_INTERVAL = 1.0      # seconds
ACK_THRESHOLD = 4       # send ack when this many pending
CHUNK_RAW_DEFAULT = 4096

def md5_bytes(b: bytes) -> str:
    import hashlib
    h = hashlib.md5(); h.update(b); return h.hexdigest()

def send_raw_bytes(nrf, buf: bytes):
    for i in range(0, len(buf), CHUNK_SIZE):
        chunk = buf[i:i+CHUNK_SIZE]
        nrf.send(chunk)
        nrf.wait_until_sent()

def collect_n_bytes_after_header(initial_buf: bytearray, rest_buf: bytes, need: int, nrf):
    """
    Ensure we collect exactly `need` bytes AFTER the header.
    initial_buf is the bytearray that currently contains leftover header bytes (we will mutate it).
    rest_buf is the bytes that remain immediately after the header in that payload.
    Returns (collected_bytes, remainder_buffer) where remainder_buffer is the bytes that follow the collected section.
    """
    collected = bytearray()
    # first, use rest_buf
    if rest_buf:
        take = min(len(rest_buf), need)
        collected.extend(rest_buf[:take])
        remaining_from_rest = rest_buf[take:]
        need -= take
    else:
        remaining_from_rest = b''

    # now, if still need more bytes, keep reading radio payloads
    buffer_tail = bytearray(remaining_from_rest)
    while need > 0:
        # get next payload
        while not nrf.data_ready():
            time.sleep(0.001)
        payload = nrf.get_payload()
        take = min(len(payload), need)
        collected.extend(payload[:take])
        if take < len(payload):
            buffer_tail.extend(payload[take:])
        need -= take

    # return collected data and remainder bytes (as bytearray)
    return bytes(collected), bytearray(buffer_tail)

def parse_json_messages_from_bytesbuf(buf: bytearray):
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
            pass
        del buf[:idx + len(HEADER_TERMINATOR)]
    return msgs, buf

def receiver_loop(pi, nrf, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    header_buf = bytearray()
    transfer_meta = None
    tmp_path = None
    meta_path = None
    received = set()
    pending_acks = []
    last_ack_time = time.time()

    print("Receiver listening for incoming transfers...")

    try:
        while True:
            if nrf.data_ready():
                payload = nrf.get_payload()   # 32 bytes
                header_buf.extend(payload)

                # extract all headers we can
                msgs, header_buf = parse_json_messages_from_bytesbuf(header_buf)
                for header in msgs:
                    htype = header.get('type')
                    if htype == 'file':
                        transfer_meta = header
                        filename = transfer_meta['filename']
                        tmp_path = os.path.join(output_dir, filename + ".partial")
                        meta_path = os.path.join(output_dir, filename + ".meta.json")
                        total_chunks = transfer_meta.get('total_chunks')
                        chunk_raw_size = transfer_meta.get('chunk_raw_size', CHUNK_RAW_DEFAULT)
                        orig_size = transfer_meta.get('orig_size')

                        # prepare partial file and persistent meta
                        if not os.path.exists(tmp_path):
                            with open(tmp_path, 'wb') as t:
                                t.truncate(orig_size)
                        if os.path.exists(meta_path):
                            with open(meta_path, 'r') as mf:
                                meta = json.load(mf)
                                received = set(int(x) for x in meta.get('received', []))
                        else:
                            received = set()
                            with open(meta_path, 'w') as mf:
                                json.dump({'received': []}, mf)

                        print(f"Receiving file {filename}: orig_size={orig_size} total_chunks={total_chunks} chunk_raw={chunk_raw_size}")
                    elif htype == 'chunk':
                        # When parsing a chunk header, the rest of the bytes not consumed in header_buf
                        # may already include part of the compressed payload. Use collect_n_bytes_after_header.
                        idx_chunk = int(header['idx'])
                        comp_size = int(header['comp_size'])
                        orig_chunk_size = int(header['orig_size'])
                        chunk_md5 = header.get('chunk_md5')

                        # At this point header_buf contains "rest" after the header terminator (if any)
                        rest = bytes(header_buf)
                        comp_bytes, remainder = collect_n_bytes_after_header(header_buf, rest, comp_size, nrf)
                        # replace header_buf with remainder (already a bytearray)
                        header_buf = remainder

                        if idx_chunk in received:
                            # already have it; queue ack
                            pending_acks.append(idx_chunk)
                            print(f"Received duplicate chunk {idx_chunk}, already stored.")
                            continue

                        # try decompress
                        try:
                            decomp = zstd.ZstdDecompressor().decompress(comp_bytes)
                        except Exception as e:
                            print(f"[ERROR] Decompress failed for chunk {idx_chunk}: {e}")
                            # save compressed for debug
                            dbg_fn = os.path.join(output_dir, f"{transfer_meta['filename']}.chunk{idx_chunk}.zst")
                            with open(dbg_fn, 'wb') as df:
                                df.write(comp_bytes)
                            continue

                        if len(decomp) != orig_chunk_size:
                            print(f"[ERROR] Size mismatch chunk {idx_chunk}: got {len(decomp)} expected {orig_chunk_size}")
                            bad_fn = os.path.join(output_dir, f"{transfer_meta['filename']}.chunk{idx_chunk}.bad")
                            with open(bad_fn, 'wb') as bf:
                                bf.write(decomp)
                            continue

                        # md5 check
                        if chunk_md5:
                            if md5_bytes(decomp) != chunk_md5:
                                print(f"[ERROR] MD5 mismatch chunk {idx_chunk}.")
                                continue

                        # write to partial file at correct offset
                        with open(tmp_path, 'r+b') as t:
                            t.seek(idx_chunk * chunk_raw_size)
                            t.write(decomp)

                        received.add(idx_chunk)
                        pending_acks.append(idx_chunk)
                        # persist metadata
                        with open(meta_path, 'w') as mf:
                            json.dump({'received': sorted(list(received))}, mf)
                        print(f"Chunk {idx_chunk} written ({len(decomp)} bytes). Received {len(received)}/{total_chunks} chunks.")

                    elif htype == 'end':
                        # optional: check completeness
                        if transfer_meta and total_chunks and len(received) == total_chunks:
                            final = os.path.join(output_dir, transfer_meta['filename'])
                            os.replace(tmp_path, final)
                            try:
                                os.remove(meta_path)
                            except Exception:
                                pass
                            print(f"Transfer complete: {final}")
                        else:
                            print("End header received but transfer incomplete or no active transfer_meta.")
                    elif htype == 'ack':
                        # If receiver ever receives ack messages (unlikely), ignore
                        pass

            # send ACKs periodically or when pending_acks big enough
            now = time.time()
            if pending_acks and (now - last_ack_time >= ACK_INTERVAL or len(pending_acks) >= ACK_THRESHOLD):
                # deduplicate and send
                to_ack = sorted(set(pending_acks))
                ack_msg = {'type':'ack', 'received': to_ack}
                try:
                    send_raw_bytes(nrf, json.dumps(ack_msg).encode('utf-8') + HEADER_TERMINATOR)
                except Exception as e:
                    print(f"Error sending ACK: {e}")
                pending_acks = []
                last_ack_time = now

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("Receiver interrupted by user.")
    except Exception:
        traceback.print_exc()
    finally:
        print("Receiver shutting down.")

def main():
    parser = argparse.ArgumentParser(description="Robust NRF24 Receiver (chunked zstd with ACKs)")
    parser.add_argument('-n','--hostname', default='localhost')
    parser.add_argument('-p','--port', type=int, default=8888)
    parser.add_argument('address', nargs='?', default='FILEX', help="5-char NRF24 address")
    parser.add_argument('output_dir', nargs='?', default='received_files', help="Directory to save received files")
    args = parser.parse_args()

    print(f"Connecting to pigpio at {args.hostname}:{args.port} ...")
    pi = pigpio.pi(args.hostname, args.port)
    if not pi.connected:
        print("Could not connect to pigpio daemon."); sys.exit(1)

    nrf = NRF24(pi, ce=25, payload_size=CHUNK_SIZE, channel=100,
                data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN)
    nrf.set_address_bytes(len(args.address))
    # open both pipes (we need to send ACKs back)
    nrf.open_reading_pipe(RF24_RX_ADDR.P1, args.address)
    nrf.open_writing_pipe(args.address)
    nrf.set_retransmission(15, 15)
    nrf.show_registers()

    try:
        receiver_loop(pi, nrf, args.output_dir)
    finally:
        nrf.power_down()
        pi.stop()

if __name__ == "__main__":
    main()
