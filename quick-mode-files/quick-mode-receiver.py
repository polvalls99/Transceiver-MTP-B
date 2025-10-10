import argparse
import sys
import time
import traceback

import pigpio
from nrf24 import *

#
# QUICK TEST MODE - NRF24L01 receiver to receive a file and save it to disk.
#
if __name__ == "__main__":
    print("Quick Mode Test - File Receiver.")

    # Parse command line argument.
    parser = argparse.ArgumentParser(prog="receiver-file.py", description="NRF24 File Receiver.")
    parser.add_argument('-n', '--hostname', type=str, default='localhost', help="Hostname for the Raspberry running the pigpio daemon.")
    parser.add_argument('-p', '--port', type=int, default=8888, help="Port number of the pigpio daemon.")
    parser.add_argument('address', type=str, nargs='?', default='FILEX', help="Address to listen to (5 ASCII characters).")
    parser.add_argument('output_filepath', type=str, help="Path to save the received file.")

    args = parser.parse_args()
    hostname = args.hostname
    port = args.port
    address = args.address
    output_filepath = args.output_filepath

    # Connect to pigpiod
    print(f'Connecting to GPIO daemon on {hostname}:{port} ...')
    pi = pigpio.pi(hostname, port)
    if not pi.connected:
        print("Could not connect to Raspberry Pi. Goodbye :(")
        sys.exit()
    
    # We use a 32-byte payload size and a 2Mbps data rate for maximum throughput.
    nrf = NRF24(pi, ce=25, payload_size=32, channel=100, data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN)
    nrf.set_address_bytes(len(address))
    nrf.open_reading_pipe(RF24_RX_ADDR.P1, address)

    # Show registers for debugging.
    nrf.show_registers()

    try:
        print(f"Listening on address: {address}")
        # Open the output file in binary write mode ('wb').
        with open(output_filepath, 'wb') as f:
            bytes_received = 0
            while True:
                # Wait for data to arrive.
                if nrf.data_ready():
                    payload = nrf.get_payload()
                    
                    # If the payload is 0 bytes, it's the end-of-file (EOF) signal.
                    if len(payload) == 0:
                        print(f"\nEnd-of-file signal received. Total: {bytes_received} bytes.")
                        break
                    
                    # Write the received data to the file.
                    f.write(payload)
                    bytes_received += len(payload)
                    print(f"Received {bytes_received} bytes...", end='\r')

        print(f"File saved successfully to: {output_filepath}")

    except Exception as e:
        traceback.print_exc()
    finally:
        # Power down the module and close the connection.
        nrf.power_down()
        pi.stop()