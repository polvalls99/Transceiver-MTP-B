#!/usr/bin/env python3
"""
Quick Mode Auto Sender (MD5 + size-based completion)
- Waits for a USB drive containing a .txt file.
- Picks the most recent .txt file.
- Computes MD5 and file size.
- Sends a JSON header {'filename', 'size', 'md5'} + '\n\n' terminator.
- Sends file data in 32-byte chunks.
- Uses size-based completion (no empty EOF packet).

Behavior added:
- Runs in a continuous loop.
- After sending, waits for the USB mount to be removed.
- When the USB is re-plugged (any mount with a .txt), it will resend.
- This effectively "resets" on unplug.
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
    """
    Espera fins que detecta un mount amb .txt. Retorna (filepath, mount_point).
    """
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
    """
    Espera fins que el punt de muntatge 'mount_point' desaparegui (USB retirat).
    """
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


def send_file(pi, nrf, filepath, address):
    print(f"Reading file: {filepath}")
    with open(filepath, 'rb') as f:
        data = f.read()

    size = len(data)
    filename = os.path.basename(filepath)
    md5sum = compute_md5(data)

    header_obj = {'filename': filename, 'size': size, 'md5': md5sum}
    header = json.dumps(header_obj).encode('utf-8') + HEADER_TERMINATOR

    print(f"Header: {header_obj}")

    print("Sending header + file...")
    sent_bytes = 0  # count of FILE bytes sent (not counting header)
    header_pos = 0  # cursor within header bytes
    data_pos = 0    # cursor within file data

    backoff = 1

    state = 2       #2 = 2Mbps    1 = 1Mbps

    def send_next_chunk():
        """Envía exactamente un bloque (header o data) y avanza punteros si se confirma."""
        nonlocal header_pos, data_pos, sent_bytes

        # 1) Header en bloques exactos de CHUNK_SIZE
        if header_pos + CHUNK_SIZE <= len(header):
            chunk = header[header_pos:header_pos + CHUNK_SIZE]
            nrf.send(chunk)
            nrf.wait_until_sent()                   # avanza SOLO si se confirma
            header_pos += CHUNK_SIZE
            return False

        # 2) Cola de header (parcial) + arranque de datos
        if header_pos < len(header):
            remaining_header = header[header_pos:]
            need = CHUNK_SIZE - len(remaining_header)
            fill = data[data_pos:data_pos + need]
            chunk = remaining_header + fill
            nrf.send(chunk)
            nrf.wait_until_sent()
            header_pos = len(header)
            data_pos += len(fill)
            sent_bytes += len(fill)
            return False

        # 3) Datos hasta completar 'size'
        if sent_bytes >= size:
            return True
        chunk = data[data_pos : data_pos + CHUNK_SIZE]
        if not chunk:
            return True
        nrf.send(chunk)
        nrf.wait_until_sent()
        data_pos   += len(chunk)
        sent_bytes += len(chunk)
        print(f"Progress: {sent_bytes}/{size} bytes ({100*sent_bytes/max(1,size):.1f}%)", end='\r')
        return sent_bytes >= size
    
    

    # Config inicial segura
    nrf.set_data_rate(RF24_DATA_RATE.RATE_2MBPS)
    nrf.flush_tx(); nrf.flush_rx()

    
    while True:
        try:
            done = send_next_chunk()
            if done:
                break
        except TimeoutError:
            # Limpia colas siempre antes de cambiar algo
            nrf.flush_tx(); nrf.flush_rx()

            if state == 2:
                print("\nTimeout at 2 Mbps → switching to 1 Mbps and continuing.")
                nrf.set_data_rate(RF24_DATA_RATE.RATE_1MBPS)
                state = 1
                continue

            if state == 1:
                print("\nTimeout at 1 Mbps → waiting and resuming at 2 Mbps.")
                time.sleep(backoff)
                nrf.set_data_rate(RF24_DATA_RATE.RATE_2MBPS)
                state = 2
                continue

            # Ya estamos en 2 Mbps tras backoff y sigue fallando
            print("\nTimeout again at 2 Mbps. Aborting transfer.")
            try:
                nrf.show_registers()
            except Exception:
                pass
            raise

    print("\nTransfer complete.")


def main():
    parser = argparse.ArgumentParser(description="NRF24 Auto File Sender (MD5)")
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
                data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN, spi_speed=10e6)
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
                # loop continues: when a .txt is found again (possibly the same file), it'll resend
            except KeyboardInterrupt:
                print("\nUser interrupted. Exiting loop.")
                break
    finally:
        nrf.power_down()
        pi.stop()


if __name__ == "__main__":
    main()
