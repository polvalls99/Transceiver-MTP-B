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

    STATE_TO_CODE = {
        STATE_IDLE:             (0, 0, 0, 0),
        STATE_RECV_WAIT:        (0, 0, 0, 1),
        STATE_RECV_ACTIVE:      (0, 0, 1, 0),
        STATE_SEND_ACTIVE:      (0, 0, 1, 1),
        STATE_SEND_WAIT:        (0, 1, 0, 0),
        STATE_NETW_WAIT:        (0, 1, 0, 1),
        STATE_NETW_RECV_ACTIVE: (0, 1, 1, 0),
        STATE_NETW_SEND_ACTIVE: (0, 1, 1, 1),
    }

    code = STATE_TO_CODE.get(state, [0, 0, 0, 0])  # F by default just in case

    for i in range(4):
        pi.write(OUT_GPIO_7SEG[i], code[i])


def set_leds(pi, state):
    """
    Sets leds according to the state
    """
    rx_led = 0
    tx_led = 0
    if   state == STATE_NETW_RECV_ACTIVE or state == STATE_RECV_ACTIVE: rx_led = 1
    elif state == STATE_NETW_SEND_ACTIVE or state == STATE_SEND_ACTIVE: tx_led = 1

    pi.write(OUT_GPIO_LED_TX_ONGOING, tx_led)
    pi.write(OUT_GPIO_LED_RX_ONGOING, rx_led)


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
    pi.set_mode(OUT_GPIO_LED_PWR_ON    , pigpio.OUTPUT)
    pi.set_mode(OUT_GPIO_LED_BOOT_UP   , pigpio.OUTPUT)
    pi.set_mode(OUT_GPIO_LED_TX_ONGOING, pigpio.OUTPUT)
    pi.set_mode(OUT_GPIO_LED_RX_ONGOING, pigpio.OUTPUT)

    # Set pull up resistor
    pi.set_pull_up_down(IN_GPIO_SWITCH_NETW , pigpio.PUD_UP)
    pi.set_pull_up_down(IN_GPIO_SWITCH_RECV , pigpio.PUD_UP)
    pi.set_pull_up_down(IN_GPIO_SWITCH_SEND , pigpio.PUD_UP)
    pi.set_pull_up_down(IN_GPIO_SWITCH_SP_0 , pigpio.PUD_UP)

    # set 7 segments to outputs
    for i in range(4):
        pi.set_mode(OUT_GPIO_7SEG[i], pigpio.OUTPUT)

    # declare child process
    t = threading.Thread(target=sender_auto.run())

    # initialize switch read value
    sw_netw = 1
    sw_send = 1
    sw_recv = 1

    # indicate that we are booted up
    pi.write(OUT_GPIO_LED_PWR_ON , 1)
    pi.write(OUT_GPIO_LED_BOOT_UP, 1)

    while True:
        sw_netw = pi.read(IN_GPIO_SWITCH_NETW)
        sw_send = pi.read(IN_GPIO_SWITCH_SEND)
        sw_recv = pi.read(IN_GPIO_SWITCH_RECV)

        # Remeber that the buttons are in pull up, so read values are inverted
        if sw_netw and sw_recv and sw_send:
            cfg.set_mode(cfg.MODE_IDLE)

            if t.is_alive():
                t.join()

            # turn off LEDs

        elif not sw_netw and cfg.APP_MODE != cfg.MODE_NETWORK:
            cfg.set_mode(cfg.MODE_NETWORK)

            # spawn network mode thread
            if t.is_alive():
                t.join()

            # FIXME: commenting network mode as it is not implemented yet
            #t = threading.Thread(target=network.run())
            #t.start()

        elif not sw_send and cfg.APP_MODE != cfg.MODE_SENDER:
            cfg.set_mode(cfg.MODE_SEND)

            # spawn recv mode thread
            if t.is_alive():
                t.join()

            t = threading.Thread(target=sender_auto.run())
            t.start()

        elif not sw_recv and cfg.APP_MODE != cfg.MODE_RECEIVER:
            cfg.set_mode(cfg.MODE_RECV)

            # spawn network mode thread
            if t.is_alive():
                t.join()

            t = threading.Thread(target=receiver_auto.run())
            t.start()

        # Handle indicator output
        set_7seg_state(pi, cfg.STATE)
        set_leds(pi, cfg.STATE)


