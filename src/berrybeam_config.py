# Initialize the global mode variable. Default it to None or a sensible default.
MODE_RECEIVER = 1
MODE_SENDER = 2
MODE_NETWORK = 3

APP_MODE = 0

def set_mode(mode):
    """
    Sets the application's global operating mode.
    This is the ONLY function that should write to APP_MODE.
    """
    global APP_MODE
    valid_modes = [MODE_RECEIVER, MODE_SENDER, MODE_NETWORK]
    
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode specified: {mode}. Must be one of {valid_modes}")

    APP_MODE = mode
    print(f"Configuration mode set to: {APP_MODE}")
