#!/usr/bin/env python3
"""
Quick Mode Auto Sender (MD5 + size-based completion) with IRQ pull-up
- Busca .txt en USB, envía header JSON+'\n\n' y luego los datos en trozos de 32B
- Fallback de 2 Mbps a 1 Mbps en TimeoutError y regreso a 2 Mbps tras espera
- IRQ: configura PUD_UP en GPIO dado; la lógica de envío sigue con wait_until_sent()
"""
import argparse, sys, time, json, os, hashlib, traceback
import pigpio
from nrf24 import *

HEADER_TERMINATOR = b'\n\n'
CHUNK_SIZE = 32
POLL_INTERVAL = 1.0

def find_usb_mounts():
    mounts = []
    try:
        with open('/proc/mounts','r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    m = parts[1]
                    if m.startswith('/media/') or m.startswith('/mnt/'):
                        mounts.append(m)
    except Exception: pass
    return mounts

def find_most_recent_txt(m):
    cands = []
    for root, _, files in os.walk(m):
        for fn in files:
            if fn.lower().endswith('.txt'):
                full = os.path.join(root, fn)
                try:
                    cands.append((os.path.getmtime(full), full))
                except Exception: pass
    if not cands: return None
    cands.sort(reverse=True)
    return cands[0][1]

def wait_for_usb_and_get_txt():
    print("Waiting for a USB drive containing a .txt file...")
    while True:
        mounts = find_usb_mounts()
        if mounts:
            for m in mounts:
                c = find_most_recent_txt(m)
                if c:
                    print(f"Found .txt on {m}: {c}")
                    return c, m
        time.sleep(POLL_INTERVAL)

def wait_for_unplug(m):
    print(f"Waiting for {m} to be removed to reset...")
    while True:
        if m not in find_usb_mounts(): print(f"{m} removed."); return
        time.sleep(POLL_INTERVAL)

def md5sum(b):
    h = hashlib.md5(); h.update(b); return h.hexdigest()

def send_file(pi, nrf, path, address):
    print(f"Reading file: {path}")
    with open(path,'rb') as f: data = f.read()
    size = len(data); filename = os.path.basename(path); md5 = md5sum(data)
    header_obj = {'filename': filename, 'size': size, 'md5': md5}
    header = json.dumps(header_obj).encode('utf-8') + HEADER_TERMINATOR
    print(f"Header: {header_obj}")

    print("Sending header + file...")
    sent_bytes = 0; header_pos = 0; data_pos = 0
    backoff = 1; state = 2  # 2=2Mbps, 1=1Mbps

    def next_chunk():
        nonlocal header_pos, data_pos, sent_bytes
        if header_pos + CHUNK_SIZE <= len(header):
            chunk = header[header_pos:header_pos+CHUNK_SIZE]
            nrf.send(chunk); nrf.wait_until_sent()
            header_pos += CHUNK_SIZE; return False
        if header_pos < len(header):
            rem = header[header_pos:]; need = CHUNK_SIZE - len(rem)
            fill = data[data_pos:data_pos+need]
            chunk = rem + fill
            nrf.send(chunk); nrf.wait_until_sent()
            header_pos = len(header); data_pos += len(fill); sent_bytes += len(fill)
            return False
        if sent_bytes >= size: return True
        chunk = data[data_pos:data_pos+CHUNK_SIZE]
        if not chunk: return True
        nrf.send(chunk); nrf.wait_until_sent()
        data_pos += len(chunk); sent_bytes += len(chunk)
        print(f"Progress: {sent_bytes}/{size} bytes ({100*sent_bytes/max(1,size):.1f}%)", end='\r')
        return sent_bytes >= size

    nrf.set_data_rate(RF24_DATA_RATE.RATE_2MBPS)
    nrf.flush_tx(); nrf.flush_rx()

    while True:
        try:
            if next_chunk(): break
        except TimeoutError:
            nrf.flush_tx(); nrf.flush_rx()
            if state == 2:
                print("\nTimeout at 2 Mbps -> 1 Mbps.")
                nrf.set_data_rate(RF24_DATA_RATE.RATE_1MBPS); state = 1; continue
            if state == 1:
                print("\nTimeout at 1 Mbps -> wait then 2 Mbps.")
                time.sleep(backoff)
                nrf.set_data_rate(RF24_DATA_RATE.RATE_2MBPS); state = 2; continue
            print("\nTimeout again at 2 Mbps. Aborting."); 
            try: nrf.show_registers()
            except Exception: pass
            raise
    print("\nTransfer complete.")

def main():
    p = argparse.ArgumentParser(description="NRF24 Auto File Sender (MD5) + optional IRQ pull-up")
    p.add_argument('-n','--hostname', default='localhost')
    p.add_argument('-p','--port', type=int, default=8888)
    p.add_argument('--irq', type=int, default=24, help="GPIO IRQ para PUD_UP. Usa -1 para omitir.")
    p.add_argument('address', nargs='?', default='FILEX')
    args = p.parse_args()

    print(f"Connecting pigpio {args.hostname}:{args.port}")
    pi = pigpio.pi(args.hostname, args.port)
    if not pi.connected:
        print("pigpio not connected"); sys.exit(1)

    if args.irq >= 0:
        try:
            pi.set_mode(args.irq, pigpio.INPUT)
            pi.set_pull_up_down(args.irq, pigpio.PUD_UP)
            print(f"IRQ line pull-up on GPIO{args.irq}")
        except Exception as e:
            print(f"IRQ GPIO setup failed: {e}")

    nrf = NRF24(pi, ce=25, payload_size=CHUNK_SIZE, channel=100,
                data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN, spi_speed=10e6)
    nrf.set_address_bytes(len(args.address))
    nrf.set_retransmission(15, 15)
    nrf.open_writing_pipe(args.address)
    nrf.show_registers()

    try:
        while True:
            try:
                txt_path, mnt = wait_for_usb_and_get_txt()
                try:
                    send_file(pi, nrf, txt_path, args.address)
                except Exception:
                    traceback.print_exc()
                    print("Error during transmission. Waiting for next removal/insert.")
                wait_for_unplug(mnt)
            except KeyboardInterrupt:
                print("\nUser interrupted."); break
    finally:
        nrf.power_down(); pi.stop()

if __name__ == "__main__":
    main()
