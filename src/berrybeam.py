#!/usr/bin/env python3
"""
Quick Mode/Ntw mode/Fast mode Test Wrapper
- Launches either the sender or the receiver script automatically.
Usage:
  python3 quick-mode-test.py sender
  python3 quick-mode-test.py receiver
"""

import argparse
import sys
import receiver_auto
import sender_auto
import berrybeam_config as cfg

# --- 1. Define the Mode Functions ---

def run_sender(args):
    """Function to run when mode is 'sender'."""
    print("--- 📨 SENDER MODE INITIATED ---")
    print(f"Args received: {args}")

    # Example specific argument for sender
    cfg.set_mode(cfg.MODE_SENDER)
    sender_auto.run(hostname=args.hostname, port=args.port, address=args.address)
    print(f"Listening on port: {args.port}")


def run_receiver(args):
    """Function to run when mode is 'receiver'."""
    print("--- 📥 RECEIVER MODE INITIATED ---")
    print(f"Args received: {args}")

    # Example specific argument for receiver
    cfg.set_mode(cfg.MODE_RECEIVER)
    receiver_auto.run(hostname=args.hostname, port=args.port, address=args.address, output_dir=args.output_dir)
    print(f"Listening on port: {args.port}")


def run_network(args):
    """Function to run when mode is 'network'."""
    print("--- 🌐 NETWORK MODE INITIATED ---")
    print(f"Args received: {args}")

    # Example specific argument for network
    cfg.set_mode(cfg.NETWORK)
    print(f"Configuring interface: {args.interface}")


def run_standalone(args):
    """Function to run when mode is 'standalone'."""
    print("--- ⚙️ STANDALONE MODE INITIATED ---")
    print(f"Args received: {args}")

    cfg.set_mode(cfg.RECEIVER)
    # Example specific argument for standalone
    print(f"Processing data locally: {args.data_path}")

# --- 2. Main Parser Setup ---

def main():
    parser = argparse.ArgumentParser(
        description="Run the program in different modes (sender, receiver, network, or standalone)."
    )

    # Use add_subparsers to define the different modes
    subparsers = parser.add_subparsers(
        dest='mode', 
        required=True,
        help='The operational mode for the script'
    )
    
    # ----------------------------------------------------
    # 1. 'sender' mode
    # ----------------------------------------------------
    parser_sender = subparsers.add_parser(
        'sender', 
        help='NRF24 Auto File Sender (MD5)'
    )
    # Add a specific argument for the sender
    parser.add_argument('-n', '--hostname', default='localhost', help="Hostname for pigpio daemon")
    parser.add_argument('-p', '--port', type=int, default=8888, help="Port for pigpio daemon")
    parser.add_argument('address', nargs='?', default='FILEX', help="5-char NRF24 address")
    # Set the function to be executed for this mode
    parser_sender.set_defaults(func=run_sender)

    # ----------------------------------------------------
    # 2. 'receiver' mode
    # ----------------------------------------------------
    parser_receiver = subparsers.add_parser(
        'receiver', 
        help='Run the program as a data receiver'
    )
    # Add a specific argument for the receiver
    parser_receiver.add_argument('-n', '--hostname', default='localhost', help="Hostname for pigpio daemon")
    parser_receiver.add_argument('-p', '--port', type=int, default=8888, help="Port for pigpio daemon")
    parser_receiver.add_argument('address', nargs='?', default='FILEX', help="5-char NRF24 address")
    parser_receiver.add_argument('output_dir', nargs='?', default='received_files', help="Directory to save received files")

    # Set the function to be executed for this mode
    parser_receiver.set_defaults(func=run_receiver)

    # ----------------------------------------------------
    # 3. 'network' mode
    # ----------------------------------------------------
    parser_network = subparsers.add_parser(
        'network', 
        help='Run the program in general network configuration mode'
    )
    # Add a specific argument for the network mode
    parser_network.add_argument(
        'dummy', 
        help='Currently unused, but we might want to pass some args to standalone in the future'
    )
    # Set the function to be executed for this mode
    parser_network.set_defaults(func=run_network)
    
    # ----------------------------------------------------
    # 4. 'standalone' mode
    # ----------------------------------------------------
    parser_standalone = subparsers.add_parser(
        'standalone', 
        help='Run the program in auto mode, letting the IO buttons in the raspberry to handle operation'
    )
    # Add a specific argument for the standalone mode
    parser_standalone.add_argument(
        'dummy', 
        help='Currently unused, but we might want to pass some args to standalone in the future'
    )
    # Set the function to be executed for this mode
    parser_standalone.set_defaults(func=run_standalone)


    # --- 3. Parse and Run ---
    args = parser.parse_args()

    # Check if a function ('func') was set by one of the subparsers
    if hasattr(args, 'func'):
        # Execute the function associated with the chosen subcommand/mode
        try:
            args.func(args)
        except KeyboardInterrupt:
            print("\n🛑 Interrupted by user.")
       # except Exception as e:
       #     print(f"❌ Error while running: {e}")

    else:
        # This block is theoretically unreachable because of required=True, 
        # but is good practice for safety.
        parser.print_help()
        sys.exit(1)

if __name__ == '__main__':
    main()
