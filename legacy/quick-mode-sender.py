import argparse
import sys
import time
import traceback
import os
import json
import hashlib

import pigpio
from nrf24 import *

#
# QUICK TEST MODE - NRF24L01 sender to read a file and send it as fast as possible.
# Now includes: header (filename + filesize) and MD5 at end.
#
if __name__ == "__main__":
    print("Quick Mode Test - File Sender (with filename + MD5).")

    # Parse command line argument.
    parser = argparse.ArgumentParser(prog="sender-file.py", description="NRF24 File Sender.")
    parser.add_argument('-n', '--hostname', type=str, default='localhost', help="Hostname for the Raspberry running the pigpio daemon.")
    parser.add_argument('-p', '--port', type=int, default=8888, help="Port number of the pigpio daemon.")
    parser.add_argument('-a', '--address', type=str, nargs='?', default='FILEX', help="Address to send to (5 ASCII characters).")
    parser.add_argument('-f', '--filepath',type=str, help="Path of the file to send.")

    args = parser.parse_args()
    hostname = args.hostname
    port = args.port
    address = args.address
    filepath = args.filepath

    # Connect to pigpiod
    print(f'Connecting to GPIO daemon on {hostname}:{port} ...')
    pi = pigpio.pi(hostname, port)
    if not pi.connected:
        print("Could not connect to Raspberry Pi. Goodbye :(")
        sys.exit()

    # We use a 32-byte payload size and a 2Mbps data rate for maximum throughput.
    nrf = NRF24(pi, ce=25, payload_size=32, channel=100, data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN)
    nrf.set_address_bytes(len(address))
    nrf.set_retransmission(15, 15)
    nrf.open_writing_pipe(address)

    # Show registers for debugging.
    nrf.show_registers()

    try:
        # Read file in binary mode.
        print(f"Reading file: {filepath}")
        with open(filepath, 'rb') as f:
            file_data = f.read()

        file_size = len(file_data)
        filename = os.path.basename(filepath)
        print(f"File read correctly. Total size: {file_size} bytes.")
        print(f"Sending to address: {address}")

        # Compute MD5 hex digest (to send at the end).
        md5_hex = hashlib.md5(file_data).hexdigest()  # 32-char ascii

        # Prepare header (JSON): contains filename and filesize.
        header_obj = {
            "filename": filename,
            "filesize": file_size
        }
        header_bytes = json.dumps(header_obj).encode('utf-8')
        header_len = len(header_bytes)

        # Helper to send arbitrary bytes in 32-byte chunks (respects payload_size).
        chunk_size = 32

        def send_bytes_stream(bdata, description=None):
            total = len(bdata)
            sent = 0
            while sent < total:
                chunk = bdata[sent:sent + chunk_size]
                nrf.send(chunk)
                try:
                    nrf.wait_until_sent()
                except TimeoutError:
                    raise TimeoutError(f"Timeout while sending {description or 'data'} at byte {sent}.")
                sent += len(chunk)


        # Protocol:
        # 1) send 4-byte big-endian header length
        # 2) send header_bytes (JSON) (can be split across many chunks)
        # 3) send file_data in chunks (as before)
        # 4) send MD5 as ASCII bytes prefixed by a 1-byte marker 'M' (so receiver can detect)
        #
        # Note: receiver must read 4 bytes -> header_len, then header_len bytes, then filesize bytes, then
        # read final MD5 marker+hex.

        # 1) send 4-byte header length
        header_len_bytes = header_len.to_bytes(4, byteorder='big')
        send_bytes_stream(header_len_bytes, description="header length")

        # 2) send header itself
        send_bytes_stream(header_bytes, description="header")

        # 3) send file data in chunks (and print progress)
        chunks_sent = 0
        file_total = file_size
        if file_total == 0:
            print("Warning: file is empty (0 bytes).")

        # Send file data using same chunk_size; use progress bar based on chunks sent
        sent_bytes = 0
        bar_length = 50
        while sent_bytes < file_total:
            chunk = file_data[sent_bytes:sent_bytes + chunk_size]
            nrf.send(chunk)
            try:
                nrf.wait_until_sent()
                sent_bytes += len(chunk)
                chunks_sent += 1
                progress = min(100, (sent_bytes * 100) / file_total if file_total else 100)
                filled_len = int(bar_length * progress // 100)
                bar = '█' * filled_len + '-' * (bar_length - filled_len)
                print(f'Progress: |{bar}| {progress:.1f}%', end='\r')
            except TimeoutError:
                print(f"\nError: Timeout on file chunk after sending {sent_bytes} bytes.")
                nrf.power_down()
                pi.stop()
                sys.exit(1)

        # 4) Send an MD5 footer. We'll send: b'M' + md5_hex_bytes
        md5_payload = b'M' + md5_hex.encode('ascii')
        send_bytes_stream(md5_payload, description="md5")

        # (Optional) Send an empty packet to signal end-of-transmission
        nrf.send(b'')
        nrf.wait_until_sent()

        print("\nTransfer complete.")
        print(f"Sent filename: {filename}")
        print(f"Sent filesize: {file_size} bytes")
        print(f"Sent MD5: {md5_hex}")

    except Exception as e:
        traceback.print_exc()
    finally:
        # Power down the module and close the connection.
        nrf.power_down()
        pi.stop()
