"""
Quick Mode Auto Receiver (MD5 + size-based completion)
- Listens for NRF24 transmissions.
- Receives a JSON header {'filename', 'size', 'md5'} ending with '\n\n'.
- Receives file data until 'size' bytes are reached (no EOF packet).
- Computes MD5 and verifies integrity.
- Saves locally, and copies automatically to USB when one is detected.
"""

import argparse
import sys
import time
import json
import os
import hashlib
import traceback
import shutil

import pigpio
from nrf24 import *

import berrybeam_config as cfg

HEADER_TERMINATOR = b'\n\n'
CHUNK_SIZE = 32

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

def compute_md5_bytes(data_bytes):
    h = hashlib.md5()
    h.update(data_bytes)
    return h.hexdigest()

def clear_directory(dir_path):
    """Remove all contents of dir_path but keep the directory itself."""
    if not os.path.isdir(dir_path):
        return
    for name in os.listdir(dir_path):
        full = os.path.join(dir_path, name)
        try:
            if os.path.islink(full) or os.path.isfile(full):
                os.remove(full)
            elif os.path.isdir(full):
                shutil.rmtree(full)
        except Exception:
            # best-effort: ignore errors during cleanup
            pass

def run(hostname='localhost', port=8888, address='FILEX', output_dir='received_files'):
    """
    Initializes and runs the NRF24 file receiving process.

    Args:
        output_dir (str): Directory where the received files will be saved (default: 'received_files').
        address (str): The 5-character NRF24 radio address to listen on (default: 'FILEX').
        hostname (str): The hostname for the pigpio daemon connection (default: 'localhost').
        port (int): The port number for the pigpio daemon connection (default: 8888).
    """

    # Ensure output_dir exists and is empty for this session
    os.makedirs(output_dir, exist_ok=True)
    clear_directory(output_dir)
    print(f"Session storage ready: {output_dir} (cleared)")

    print(f"Connecting to pigpio daemon on {hostname}:{port} ...")
    pi = pigpio.pi(hostname, port)
    if not pi.connected:
        print("Could not connect to pigpio daemon. Exiting.")
        sys.exit(1)

    nrf = NRF24(pi, ce=25, payload_size=CHUNK_SIZE, channel=100,
                data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN, spi_speed=10e6)
    nrf.set_address_bytes(len(address))
    nrf.open_reading_pipe(RF24_RX_ADDR.P1, address)
    nrf.show_registers()

    try:
        print(f"Listening on address: {address}")
        header_buf = bytearray()
        receiving = False
        expected_size = None
        filename = None
        md5_expected = None
        file_bytes = bytearray()
        last_copy_check = 0
        a = 0

        while cfg.APP_MODE == cfg.MODE_RECEIVER:
            if nrf.data_ready():
                payload = nrf.get_payload()

                if not receiving:
                    header_buf.extend(payload)
                    idx = header_buf.find(HEADER_TERMINATOR)
                    if idx != -1:
                        header_bytes = header_buf[:idx]
                        rest = header_buf[idx + len(HEADER_TERMINATOR):]
                        try:
                            header = json.loads(header_bytes.decode('utf-8'))
                            filename = header.get('filename', 'received_file.bin')
                            expected_size = int(header.get('size', 0))
                            md5_expected = header.get('md5')
                            print(f"\nHeader parsed: filename={filename}, size={expected_size}, md5={md5_expected}")
                        except Exception:
                            print("Header parsing failed. Resetting.")
                            header_buf = bytearray()
                            continue

                        receiving = True
                        if rest:
                            take = min(len(rest), expected_size)
                            file_bytes.extend(rest[:take])
                            print(f"Received {len(file_bytes)}/{expected_size} bytes...", end='\r')
                else:
                    remaining = expected_size - len(file_bytes)
                    if remaining > 0:
                        take = min(len(payload), remaining)
                        file_bytes.extend(payload[:take])
                        print(f"Received {len(file_bytes)}/{expected_size} bytes...", end='\r')

                if receiving and expected_size and len(file_bytes) >= expected_size:
                    print(f"\nExpected bytes reached ({expected_size}). Verifying MD5...")
                    md5_actual = compute_md5_bytes(file_bytes)
                    if md5_expected:
                        if md5_actual == md5_expected:
                            print(f"MD5 OK: {md5_actual}")
                        else:
                            print(f"MD5 mismatch! Expected {md5_expected}, got {md5_actual}")
                            #Mejora
                            '''
                            try: os.remove(save_path)
                            except: pass
                            header_buf = bytearray()
                            file_bytes = bytearray()
                            receiving = False
                            expected_size = None
                            filename = None
                            md5_expected = None
                            continue
                            '''
                    else:
                        print(f"No MD5 in header. Computed: {md5_actual}")

                    os.makedirs(output_dir, exist_ok=True)
                    save_path = os.path.join(output_dir, filename)
                    with open(save_path, 'wb') as f:
                        f.write(file_bytes)
                    print(f"Saved file to {save_path}")
                    a = 1
                    mounts = find_usb_mounts()
                    if mounts:
                        dest_root = mounts[0]
                        dest_dir = os.path.join(dest_root, 'received_files')
                        os.makedirs(dest_dir, exist_ok=True)
                        dest_path = os.path.join(dest_dir, filename)
                        try:
                            shutil.copy2(save_path, dest_path)
                            print(f"Copied file to USB: {dest_path}")
                        except Exception:
                            print("USB copy failed. Will retry later.")

                    header_buf = bytearray()
                    receiving = False
                    expected_size = None
                    filename = None
                    md5_expected = None
                    file_bytes = bytearray()

            else:
                time.sleep(0.01)

            now = time.time()
            if now - last_copy_check > 1.0:
                last_copy_check = now
                mounts = find_usb_mounts()
                if mounts and a==1:
                    usb = mounts[0]
                    if os.path.isdir(output_dir):
                        for fname in os.listdir(output_dir):
                            local_file = os.path.join(output_dir, fname)
                            if os.path.isfile(local_file):
                                dest_dir = os.path.join(usb, 'received_files')
                                os.makedirs(dest_dir, exist_ok=True)
                                dest = os.path.join(dest_dir, fname)
                                try:
                                    if (not os.path.exists(dest)) or (
                                        os.path.getmtime(local_file) > os.path.getmtime(dest)
                                    ):
                                        shutil.copy2(local_file, dest)
                                        print(f"Copied pending file to USB: {dest}")
                                        a = 0
                                except Exception:
                                    pass

    except KeyboardInterrupt:
        print("\nUser interrupted.")
    except Exception:
        traceback.print_exc()
    finally:
        nrf.power_down()
        pi.stop()
