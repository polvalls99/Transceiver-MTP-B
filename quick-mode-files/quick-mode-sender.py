import argparse
import sys
import time
import traceback

import pigpio
from nrf24 import *

#
# QUICK TEST MODE - NRF24L01 sender to read a file and send it as fast as possible.
#
if __name__ == "__main__":
    print("Quick Mode Test - File Sender.")

    # Parse command line argument.
    parser = argparse.ArgumentParser(prog="sender-file.py", description="NRF24 File Sender.")
    parser.add_argument('-n', '--hostname', type=str, default='localhost', help="Hostname for the Raspberry running the pigpio daemon.")
    parser.add_argument('-p', '--port', type=int, default=8888, help="Port number of the pigpio daemon.")
    parser.add_argument('address', type=str, nargs='?', default='FILEX', help="Address to send to (5 ASCII characters).")
    parser.add_argument('filepath', type=str, help="Path of the file to send.")

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
    # PA Level remains at MIN because the tests are at close range.
    nrf = NRF24(pi, ce=25, payload_size=32, channel=100, data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN)
    nrf.set_address_bytes(len(address))
    nrf.set_retransmission(15, 15)
    nrf.open_writing_pipe(address)

    # Show registers for debugging.
    nrf.show_registers()

    try:
        # We read the entire file in binary mode ('rb').
        print(f"Reading file: {filepath}")
        with open(filepath, 'rb') as f:
            file_data = f.read()
        
        file_size = len(file_data)
        print(f"File read correctly. Total size: {file_size} bytes.")
        print(f"Sending to address: {address}")

        # We send the file in 32-byte chunks.
        chunk_size = 32
        chunks_sent = 0
        for i in range(0, file_size, chunk_size):
            chunk = file_data[i:i + chunk_size]
            nrf.send(chunk)
            try:
                # Wait for the acknowledgment (Auto-ACK) from the receiver.
                nrf.wait_until_sent()
                chunks_sent += 1
                # Print the progress.
                progress = (chunks_sent * chunk_size * 100) / file_size
                print(f"Progress: {min(100, progress):.2f}%", end='\r')

            except TimeoutError:
                print(f"Error: Timeout on chunk {chunks_sent}. Retrying or aborting...")
                # Retry logic could be added here.
                nrf.power_down()
                pi.stop()
                sys.exit(1)

        # Send an empty packet to signal the end of the transmission (EOF).
        nrf.send(b'')
        nrf.wait_until_sent()

        print("\nTransfer complete.")

    except Exception as e:
        traceback.print_exc()
    finally:
        # Power down the module and close the connection.
        nrf.power_down()
        pi.stop()