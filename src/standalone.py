# ====================================================================
# Filename: standalone.py
# Author: Andreu Roca
# Created: 03/11/25
# ====================================================================
# Description: This script remotes via SSH into both raspberries and
#              launches the command defined in the config.yml file.
# ====================================================================

import threading
import Pretest
import berrybeam_config as cfg
import pigpio
import time

# Global variables for the green and white LEDs. Allow us to toggle their values.
yellow_led = 0
green_led = 0

def set_7seg_state(pi, state):
    """
    Sets 7 segment code according to its symbol
    """

    STATE_TO_CODE = {
            cfg.STATE_IDLE         : (0, 0, 0, 0),
        cfg.STATE_RECV_WAIT        : (0, 0, 0, 1),
        cfg.STATE_RECV_ACTIVE      : (0, 0, 1, 0),
        cfg.STATE_RECV_WAIT_USB    : (0, 0, 1, 1),
        cfg.STATE_RECV_USB_DONE    : (0, 1, 0, 0),
        cfg.STATE_SEND_WAIT        : (0, 1, 0, 1),
        cfg.STATE_SEND_ACTIVE      : (0, 1, 1, 0),
        cfg.STATE_NETW_WAIT        : (0, 1, 1, 1),
        cfg.STATE_NETW_RECV_ACTIVE : (1, 0, 0, 0),
        cfg.STATE_NETW_SEND_ACTIVE : (1, 0, 0, 1),
    }

    code = STATE_TO_CODE.get(state, [1, 1, 1, 1])  # F by default, which turns off the 7 seg

    for i in range(4):
        pi.write(cfg.OUT_GPIO_7SEG[i], code[i])


def set_leds(pi, mode):
    """
    Sets leds according to the mode
    """

    global yellow_led
    global green_led

    if cfg.APP_MODE == cfg.MODE_NETWORK:
        yellow_led ^= 1
    elif cfg.APP_MODE == cfg.MODE_RECEIVER_FAST or cfg.APP_MODE == cfg.MODE_SENDER_FAST:
        green_led ^= 1
    else:
        yellow_led = 1
        green_led = 1

    pi.write(cfg.OUT_GPIO_LED_GREEN, green_led)
    pi.write(cfg.OUT_GPIO_LED_YELLOW, yellow_led)


def detect_press(pi, pin):
    """
    Detects a 0.5 second long press
    """
    if not pi.read(pin):
        for i in range(5):
            time.sleep(0.1)
            if pi.read(pin) : return 1 # No press

        # Wait until button has been released, otherwise we might crash pigpiod
        while not pi.read(pin): time.sleep(0.1)
        return 0

    return 1 # No press


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
    pi.set_mode(cfg.IN_GPIO_SWITCH_NETW, pigpio.INPUT)
    pi.set_mode(cfg.IN_GPIO_SWITCH_RECV, pigpio.INPUT)
    pi.set_mode(cfg.IN_GPIO_SWITCH_SEND, pigpio.INPUT)
    pi.set_mode(cfg.IN_GPIO_SWITCH_SP_0, pigpio.INPUT)
    #pi.set_mode(cfg.OUT_GPIO_LED_PWR_ON, pigpio.OUTPUT)
    pi.set_mode(cfg.OUT_GPIO_LED_YELLOW, pigpio.OUTPUT)
    pi.set_mode(cfg.OUT_GPIO_LED_WHITE , pigpio.OUTPUT)
    pi.set_mode(cfg.OUT_GPIO_LED_GREEN , pigpio.OUTPUT)

    # Set pull up resistor
    pi.set_pull_up_down(cfg.IN_GPIO_SWITCH_SP_0, pigpio.PUD_UP)
    pi.set_pull_up_down(cfg.IN_GPIO_SWITCH_RECV, pigpio.PUD_UP)
    pi.set_pull_up_down(cfg.IN_GPIO_SWITCH_SEND, pigpio.PUD_UP)
    pi.set_pull_up_down(cfg.IN_GPIO_SWITCH_NETW, pigpio.PUD_UP)

    # set 7 segments to outputs
    for i in range(4):
        pi.set_mode(cfg.OUT_GPIO_7SEG[i], pigpio.OUTPUT)

    # declare child process
    t = threading.Thread(target=Pretest.main)

    # initialize switch read value
    sw_netw = 1
    sw_send = 1
    sw_recv = 1
    sw_idle = 1

    # indicate that we are booted up
    #pi.write(cfg.OUT_GPIO_LED_PWR_ON , 1)
    pi.write(cfg.OUT_GPIO_LED_YELLOW, 1)
    pi.write(cfg.OUT_GPIO_LED_WHITE, 0)
    pi.write(cfg.OUT_GPIO_LED_GREEN, 0)

    # wait 1 second to give time for restistors to be set up
    time.sleep(1)

    try:
        while True:
            time.sleep(0.1)

            sw_netw = detect_press(pi, cfg.IN_GPIO_SWITCH_NETW)
            sw_send = detect_press(pi, cfg.IN_GPIO_SWITCH_SEND)
            sw_recv = detect_press(pi, cfg.IN_GPIO_SWITCH_RECV)
            sw_idle = detect_press(pi, cfg.IN_GPIO_SWITCH_SP_0)

            #print(f"sw_idle = {sw_idle}, sw_send = {sw_send}, sw_recv = {sw_recv}, sw_netw = {sw_netw}")

            # Remeber that the buttons are in pull up, so read values are inverted
            if not sw_idle and cfg.APP_MODE != cfg.STATE_IDLE:
                cfg.set_mode(cfg.MODE_IDLE)
                cfg.set_state(cfg.STATE_IDLE)

                if t.is_alive():
                    t.join()

            elif not sw_netw and cfg.APP_MODE != cfg.MODE_NETWORK:
                cfg.set_mode(cfg.MODE_NETWORK)
                cfg.set_state(cfg.STATE_KILL_THREAD)

                # spawn network mode thread
                if t.is_alive():
                    t.join()

                cfg.set_state(cfg.STATE_NETW_WAIT)

                print ("\033[33m[WARN]\033[0m Network mode not integrated, nothing to do...")
                # FIXME: commenting network mode as it is not implemented yet
                #t = threading.Thread(target=network.run())
                #t.start()

            elif not sw_send and cfg.APP_MODE != cfg.MODE_SENDER:
                cfg.set_mode(cfg.MODE_SENDER)
                cfg.set_state(cfg.STATE_KILL_THREAD)

                # spawn recv mode thread
                if t.is_alive():
                    t.join()

                cfg.set_state(cfg.STATE_SEND_WAIT)
                t = threading.Thread(target=Pretest.main, args=(1, 0, 0))
                t.start()

            elif not sw_send and cfg.APP_MODE != cfg.MODE_SENDER_FAST:
                cfg.set_mode(cfg.MODE_SENDER_FAST)
                cfg.set_state(cfg.STATE_KILL_THREAD)

                # spawn recv mode thread
                if t.is_alive():
                    t.join()

                cfg.set_state(cfg.STATE_SEND_WAIT)
                t = threading.Thread(target=Pretest.main, args=(1, 0, 1))
                t.start()

            elif not sw_recv and cfg.APP_MODE != cfg.MODE_RECEIVER:
                cfg.set_mode(cfg.MODE_RECEIVER)
                cfg.set_state(cfg.STATE_KILL_THREAD)

                # spawn network mode thread
                if t.is_alive():
                    t.join()

                cfg.set_state(cfg.STATE_RECV_WAIT)
                t = threading.Thread(target=Pretest.main, args=(0, 0, 0))
                t.start()

            elif not sw_recv and cfg.APP_MODE != cfg.MODE_RECEIVER_FAST:
                cfg.set_mode(cfg.MODE_RECEIVER_FAST)
                cfg.set_state(cfg.STATE_KILL_THREAD)

                # spawn network mode thread
                if t.is_alive():
                    t.join()

                cfg.set_state(cfg.STATE_RECV_WAIT)
                t = threading.Thread(target=Pretest.main, args=(0, 0, 0))
                t.start()


            # Handle indicator output
            set_7seg_state(pi, cfg.STATE)
            set_leds(pi, cfg.STATE)

    except KeyboardInterrupt:
        print("\nUser interrupted.")
    except Exception:
        traceback.print_exc()
    finally:
        #pi.write(cfg.OUT_GPIO_LED_PWR_ON    , 0)
        pi.write(cfg.OUT_GPIO_LED_YELLOW, 0)
        pi.write(cfg.OUT_GPIO_LED_WHITE, 0)
        pi.write(cfg.OUT_GPIO_LED_GREEN, 0)

        for i in range(4):
            pi.write(cfg.OUT_GPIO_7SEG[i], 0)

        pi.stop()

