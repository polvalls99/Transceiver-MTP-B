# ====================================================================
# Filename: standalone.py
# Author: Andreu Roca
# Created: 03/11/25
# ====================================================================
# Description: This script remotes via SSH into both raspberries and
#              launches the command defined in the config.yml file.
# ====================================================================

import receiver_auto
import sender_auto
import berrybeam_config as cfg
import pigpio

def set_7seg_state(pi, state):
    """
    Sets 7 segment code according to its symbol
    """
    segments = [1, 1, 1, 1, 1, 1, 1] # all off by default

    if   state == STATE_IDLE:             segments = [1, 1, 1, 1, 1, 1, 1] # 0
    elif state == STATE_RECV_WAIT:        segments = [1, 1, 1, 1, 1, 1, 1] # 1
    elif state == STATE_RECV_ACTIVE:      segments = [1, 1, 1, 1, 1, 1, 1] # 1
    elif state == STATE_SEND_ACTIVE:      segments = [1, 1, 1, 1, 1, 1, 1] # 2
    elif state == STATE_SEND_WAIT:        segments = [1, 1, 1, 1, 1, 1, 1] # 3
    elif state == STATE_NETW_WAIT:        segments = [1, 1, 1, 1, 1, 1, 1] # 4
    elif state == STATE_NETW_RECV_ACTIVE: segments = [1, 1, 1, 1, 1, 1, 1] # 5
    elif state == STATE_NETW_SEND_ACTIVE: segments = [1, 1, 1, 1, 1, 1, 1] # 6

    for i in range(6):
        pi.write(OUT_GPIO_7SEG[i], segments[i])


def run(hostname='localhost', port=8888):
    """
    Top level loop the arbitrates what mode we are running in based on the GPIO input.
    It also handles the GPIO writes to the 7-segment display.

    This function invocates child threads for the NRF24 handlers.

    Args:
        hostname (str): The hostname for the pigpio daemon connection (default: 'localhost').
        port (int): The port number for the pigpio daemon connection (default: 8888).
    """

    pi = pigpio.pi(hostname, port)
    if not pi.connected:
        print("Could not connect to pigpio daemon. Exiting.")
        sys.exit(1)

    # pin initialization
    pi.set_mode(IN_GPIO_SWITCH_NETW    , pigpio.INPUT)
    pi.set_mode(IN_GPIO_SWITCH_RECV    , pigpio.INPUT)
    pi.set_mode(IN_GPIO_SWITCH_SEND    , pigpio.INPUT)
    pi.set_mode(IN_GPIO_SWITCH_SP_0    , pigpio.INPUT)
    pi.set_mode(IN_GPIO_SWITCH_SP_1    , pigpio.INPUT)
    pi.set_mode(OUT_GPIO_LED_PWR_ON    , pigpio.OUTPUT)
    pi.set_mode(OUT_GPIO_LED_BOOT_UP   , pigpio.OUTPUT)
    pi.set_mode(OUT_GPIO_LED_TX_ONGOING, pigpio.OUTPUT)
    pi.set_mode(OUT_GPIO_LED_RX_ONGOING, pigpio.OUTPUT)

    for i in range(6):
        pi.set_mode(OUT_GPIO_7SEG[i], pigpio.OUTPUT)

    # declare child process
    t = threading.Thread(target=sender_auto.run())

    # initialize switch read value
    sw_netw = 0
    sw_send = 0
    sw_recv = 0

    # indicate that we are booted up
    pi.write(OUT_GPIO_LED_BOOT_UP, 1)

    while True:
        sw_netw = pi.read(IN_GPIO_SWITCH_NETW)
        sw_send = pi.read(IN_GPIO_SWITCH_SEND)
        sw_recv = pi.read(IN_GPIO_SWITCH_RECV)

        if not sw_netw and not sw_recv and not sw_send:
            cfg.set_mode(cfg.MODE_IDLE)

            if t.is_alive():
                t.join()

            # turn off LEDs

        elif and cfg.APP_MODE != cfg.MODE_NETWORK:
            cfg.set_mode(cfg.MODE_NETWORK)

            # spawn network mode thread
            if t.is_alive():
                t.join()

            # FIXME: commenting network mode as it is not implemented yet
            #t = threading.Thread(target=network.run())
            #t.start()

        elif pi.read(IN_GPIO_SWITCH_SEND) and cfg.APP_MODE != cfg.MODE_SENDER:
            cfg.set_mode(cfg.MODE_SEND)

            # spawn recv mode thread
            if t.is_alive():
                t.join()

            t = threading.Thread(target=sender_auto.run())
            t.start()

        elif pi.read(IN_GPIO_SWITCH_RECV) and cfg.APP_MODE != cfg.MODE_RECEIVER:
            cfg.set_mode(cfg.MODE_RECV)

            # spawn network mode thread
            if t.is_alive():
                t.join()

            t = threading.Thread(target=receiver_auto.run())
            t.start()

        # Handle indicator output
        set_7seg_state(pi, cfg.STATE)


