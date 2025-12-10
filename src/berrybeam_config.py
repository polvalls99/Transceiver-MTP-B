# Initialize the global mode variable. Default it to None or a sensible default.
MODE_IDLE = 0
MODE_RECEIVER = 1
MODE_RECEIVER_FAST = 2
MODE_SENDER = 3
MODE_SENDER_FAST = 4
MODE_NETWORK = 5

# State to indicate to the 7 segment display cuz i'm too lazy to write an enum
STATE_IDLE             = 0
STATE_RECV_WAIT        = 1
STATE_RECV_ACTIVE      = 2
STATE_RECV_WAIT_USB    = 3
STATE_RECV_USB_DONE    = 4
STATE_SEND_WAIT        = 5
STATE_SEND_ACTIVE      = 6
STATE_NETW_WAIT        = 7
STATE_NETW_RECV_ACTIVE = 8
STATE_NETW_SEND_ACTIVE = 9
STATE_KILL_THREAD      = 99

# GPIO pins
IN_GPIO_SWITCH_SP_0     = 19
IN_GPIO_SWITCH_RECV     = 4
IN_GPIO_SWITCH_SEND     = 5
IN_GPIO_SWITCH_NETW     = 26
#OUT_GPIO_LED_PWR_ON     = 18
OUT_GPIO_LED_GREEN  = 12 # Green
OUT_GPIO_LED_YELLOW = 20 # Yellow
OUT_GPIO_LED_WHITE  = 16 # White
OUT_GPIO_7SEG = [23, 18, 15, 14] # index 0 is seg a, index 6 is segment g

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
    valid_modes = [MODE_IDLE, MODE_RECEIVER, MODE_RECEIVER_FAST, MODE_SENDER_FAST, MODE_SENDER, MODE_NETWORK]
    
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
    valid_states = [STATE_IDLE            ,
                    STATE_RECV_WAIT       ,
                    STATE_RECV_ACTIVE     ,
                    STATE_RECV_WAIT_USB   ,
                    STATE_RECV_USB_DONE   ,
                    STATE_SEND_WAIT       ,
                    STATE_SEND_ACTIVE     , 
                    STATE_NETW_WAIT       ,
                    STATE_NETW_RECV_ACTIVE,
                    STATE_NETW_SEND_ACTIVE,
                    STATE_KILL_THREAD]

    
    if state not in valid_states:
        raise ValueError(f"Invalid mode specified: {mode}. Must be one of {valid_modes}")

    STATE = state

    print(f"State set to: {state}")
