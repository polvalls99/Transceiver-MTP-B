#!/usr/bin/env python3
"""
Quick Mode Auto Receiver with IRQ support (MD5 + size-based completion)
- Header JSON {'filename','size','md5'} terminado en '\n\n'
- Recibe hasta 'size' bytes (sin paquete EOF)
- Verifica MD5 y copia a USB si existe
- IRQ opcional: --irq GPIO (default 24). Activo en bajo. Fallback a polling.
"""
import argparse, sys, time, json, os, hashlib, traceback, shutil, threading
import pigpio
from nrf24 import *

HEADER_TERMINATOR = b'\n\n'
CHUNK_SIZE = 32

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
    except Exception:
        pass
    return mounts

def compute_md5_bytes(b):
    h = hashlib.md5(); h.update(b); return h.hexdigest()

def clear_directory(d):
    if not os.path.isdir(d): return
    for n in os.listdir(d):
        p = os.path.join(d, n)
        try:
            if os.path.islink(p) or os.path.isfile(p): os.remove(p)
            elif os.path.isdir(p): shutil.rmtree(p)
        except Exception: pass

def main():
    p = argparse.ArgumentParser(description="NRF24 Auto File Receiver (MD5) + optional IRQ")
    p.add_argument('-n','--hostname', default='localhost')
    p.add_argument('-p','--port', type=int, default=8888)
    p.add_argument('--irq', type=int, default=24, help="GPIO IRQ activo en bajo. Usa -1 para desactivar.")
    p.add_argument('address', nargs='?', default='FILEX')
    p.add_argument('output_dir', nargs='?', default='received_files')
    args = p.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    clear_directory(args.output_dir)
    print(f"Session storage ready: {args.output_dir} (cleared)")

    print(f"Connecting pigpio {args.hostname}:{args.port}")
    pi = pigpio.pi(args.hostname, args.port)
    if not pi.connected:
        print("pigpio not connected"); sys.exit(1)

    rx_event = None
    irq_cb = None
    if args.irq >= 0:
        try:
            pi.set_mode(args.irq, pigpio.INPUT)
            pi.set_pull_up_down(args.irq, pigpio.PUD_UP)  # IRQ open-drain, activo-bajo
            rx_event = threading.Event()
            def _irq_cb(gpio, level, tick):
                if level == 0: rx_event.set()
            irq_cb = pi.callback(args.irq, pigpio.FALLING_EDGE, _irq_cb)
            print(f"IRQ enabled on GPIO{args.irq}")
        except Exception as e:
            print(f"IRQ setup failed: {e}. Using polling.")
            rx_event = None
            try:
                if irq_cb: irq_cb.cancel()
            except Exception: pass
            irq_cb = None
    else:
        print("IRQ disabled. Polling mode.")

    nrf = NRF24(pi, ce=25, payload_size=CHUNK_SIZE, channel=100,
                data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN, spi_speed=10e6)
    nrf.set_address_bytes(len(args.address))
    nrf.open_reading_pipe(RF24_RX_ADDR.P1, args.address)
    nrf.show_registers()

    header_buf = bytearray()
    receiving = False
    expected_size = None
    filename = None
    md5_expected = None
    file_bytes = bytearray()
    last_copy_check = 0.0
    copied_pending_flag = 0

    def process_payload(payload):
        nonlocal header_buf, receiving, expected_size, filename, md5_expected, file_bytes, copied_pending_flag
        if not receiving:
            header_buf.extend(payload)
            idx = header_buf.find(HEADER_TERMINATOR)
            if idx != -1:
                header_bytes = header_buf[:idx]
                rest = header_buf[idx+len(HEADER_TERMINATOR):]
                try:
                    h = json.loads(header_bytes.decode('utf-8'))
                    filename = h.get('filename','received_file.bin')
                    expected_size = int(h.get('size',0))
                    md5_expected = h.get('md5')
                    print(f"\nHeader parsed: filename={filename}, size={expected_size}, md5={md5_expected}")
                except Exception:
                    print("Header parse error. Reset.")
                    header_buf = bytearray(); return
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
                print("MD5 OK: " + md5_actual if md5_actual == md5_expected
                      else f"MD5 mismatch. expected={md5_expected} got={md5_actual}")
            else:
                print(f"No MD5 in header. Computed: {md5_actual}")

            os.makedirs(args.output_dir, exist_ok=True)
            save_path = os.path.join(args.output_dir, filename)
            with open(save_path,'wb') as f: f.write(file_bytes)
            print(f"Saved file to {save_path}")
            copied_pending_flag = 1

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

            header_buf = bytearray(); receiving = False
            expected_size = None; filename = None; md5_expected = None
            file_bytes = bytearray()

    try:
        print(f"Listening on address: {args.address}")
        while True:
            if rx_event is not None:
                if rx_event.wait(0.1):
                    rx_event.clear()
                    while nrf.data_ready():
                        payload = nrf.get_payload()
                        process_payload(payload)
            else:
                if nrf.data_ready():
                    payload = nrf.get_payload()
                    process_payload(payload)
                else:
                    time.sleep(0.01)

            now = time.time()
            if now - last_copy_check > 1.0:
                last_copy_check = now
                mounts = find_usb_mounts()
                if mounts and copied_pending_flag == 1:
                    usb = mounts[0]
                    if os.path.isdir(args.output_dir):
                        for fname in os.listdir(args.output_dir):
                            src = os.path.join(args.output_dir, fname)
                            if os.path.isfile(src):
                                dst_dir = os.path.join(usb, 'received_files')
                                os.makedirs(dst_dir, exist_ok=True)
                                dst = os.path.join(dst_dir, fname)
                                try:
                                    if (not os.path.exists(dst)) or (
                                        os.path.getmtime(src) > os.path.getmtime(dst)
                                    ):
                                        shutil.copy2(src, dst)
                                        print(f"Copied pending file to USB: {dst}")
                                        copied_pending_flag = 0
                                except Exception:
                                    pass
    except KeyboardInterrupt:
        print("\nUser interrupted.")
    except Exception:
        traceback.print_exc()
    finally:
        try:
            if irq_cb is not None: irq_cb.cancel()
        except Exception: pass
        nrf.power_down(); pi.stop()

if __name__ == "__main__":
    main()
