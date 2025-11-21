# Initialize the global mode variable. Default it to None or a sensible default.
MODE_IDLE = 0
MODE_RECEIVER = 1
MODE_SENDER = 2
MODE_NETWORK = 3

# State to indicate to the 7 segment display cuz i'm too lazy to write an enum
STATE_IDLE             = 0
STATE_RECV_WAIT        = 1
STATE_RECV_ACTIVE      = 2
STATE_SEND_WAIT        = 3
STATE_SEND_ACTIVE      = 4
STATE_NETW_WAIT        = 5
STATE_NETW_RECV_ACTIVE = 6
STATE_NETW_SEND_ACTIVE = 7

# GPIO pins
IN_GPIO_SWITCH_SP_0     = 5  # physical pin 29
IN_GPIO_SWITCH_RECV     = 6  # physical pin 31
IN_GPIO_SWITCH_SEND     = 12 # physical pin 32
IN_GPIO_SWITCH_NETW     = 13 # physical pin 33
OUT_GPIO_LED_PWR_ON     = 18 # physical pin 12, red
OUT_GPIO_LED_BOOT_UP    = 20 # physical pin 38, yellow
OUT_GPIO_LED_TX_ONGOING = 19 # physical pin 35, white
OUT_GPIO_LED_RX_ONGOING = 18 # physical pin 18, green
OUT_GPIO_7SEG = [23, 22, 27, 17] # index 0 is seg a, index 6 is segment g

# Global mode variable. DO NOT CHANGE MANUALLY, use always the hanlder function
APP_MODE = 0

# Global mode variable. DO NOT CHANGE MANUALLY, use always the hanlder function
STATE = 0

# Global variable indicating if we are sending/receiving data
RECV_ACTIVE = 0
SEND_ACTIVE = 0

def set_mode(mode):
    """
    Sets the application's global operating mode.
    This is the ONLY function that should write to APP_MODE.
    """
    global APP_MODE
    valid_modes = [MODE_IDLE, MODE_RECEIVER, MODE_SENDER, MODE_NETWORK]
    
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode specified: {mode}. Must be one of {valid_modes}")

    APP_MODE = mode
    print(f"Configuration mode set to: {APP_MODE}")


def set_state(state):
    """
    Sets the application's global state.
    The state is then read by the top level to set the 7 segment accordingly
    """
    global STATE
    valid_states = [STATE_IDLE, STATE_RECV_WAIT, STATE_RECV_ACTIVE, STATE_SEND_WAIT,
                    STATE_SEND_ACTIVE, STATE_NETW_WAIT, STATE_NETW_RECV_ACTIVE, STATE_NETW_SEND_ACTIVE]
    
    if state not in valid_states:
        raise ValueError(f"Invalid mode specified: {mode}. Must be one of {valid_modes}")

    STATE = state

    print(f"State set to: {state}")
