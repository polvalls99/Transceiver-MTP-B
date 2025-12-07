# :::: LIBRARY IMPORTS ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
from nrf24 import (
    NRF24,

    RF24_DATA_RATE,
    RF24_PA,
    RF24_RX_ADDR,
    RF24_PAYLOAD,
    RF24_CRC,
)

from pathlib import Path
import pigpio

import time
import sys
import os

from math import ceil

from hashlib import shake_256

from enum import Enum

import argparse

import berrybeam_config as cfg

os.system("sudo pigpiod")
os.system("clear")
# :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::





# :::: CONSTANTS/GLOBALS ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
CE_PIN                      = 25
RECEIVER_TIMEOUT_S          = 20
BYTES_IN_FRAME              = 30
channel_read_timeout        = 1
PERSEVERANCE                = 1000
channel_permanence_timeout  = 10
channel_tx_timeout          = 120
CUT_LENGTH                  = 1000000
ZSTD_LEVEL                  = 3

# :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::





# :::: HELPER FUNCTIONS :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
def RED(message: str)    -> str: return f"\033[31m{message}\033[0m"
def GREEN(message: str)  -> str: return f"\033[32m{message}\033[0m"
def YELLOW(message: str) -> str: return f"\033[33m{message}\033[0m"
def BLUE(message: str)   -> str: return f"\033[34m{message}\033[0m"

def ERROR(message: str) -> None: print(f"{RED('[~ERR]:')} {message}")
def SUCC(message: str)  -> None: print(f"{GREEN('[SUCC]:')} {message}")
def WARN(message: str)  -> None: print(f"{YELLOW('[WARN]:')} {message}")
def INFO(message: str)  -> None: print(f"{BLUE('[INFO]:')} {message}")
# :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::


# :::: CUSTOM ERROR :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
class StateChanged(Exception):
    pass
    #def __init__(self, message, field):
     #   super().__init__(message)
      #  self.field = field
# :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::


# :::: NODE CONFIG ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
class Role(Enum):
    TRANSMITTER = "TRANSMITTER"
    RECEIVER    = "RECEIVER"

    def __str__(self: "Role") -> str:
        return self.value

def choose_node_role() -> Role:
    while True:
        val = input(f"{YELLOW('[>>>>]:')} Please choose a role for this device [T]ransmitter, [R]eceiver: ")
        
        try:
            val = val.upper()
        except:
            continue

        if val == "T":
            INFO(f"Device set to {Role.TRANSMITTER} role")
            return Role.TRANSMITTER
            
        elif val == "R":
            INFO(f"Device set to {Role.RECEIVER} role")
            return Role.RECEIVER

def disable_auto_ack(nrf: NRF24):
    nrf.unset_ce()
    nrf._nrf_write_reg(nrf.EN_AA, 0x00)   # <<< disable auto-ack for all pipes
    nrf.set_ce()

    nrf.set_retransmission(0, 0)  # <<< disable auto-retransmissions (x+1) * 250 µs

def create_radio_object(CE_PIN) -> NRF24:
    # pigpio
    hostname = "localhost"
    port     = 8888

    pi = pigpio.pi(hostname, port)
    if not pi.connected:
        ERROR("Not connected to Raspberry Pi, exiting")
        sys.exit(1)

    # radio object
    nrf = NRF24(
        pi            = pi,
        ce            = CE_PIN,
        spi_speed     = 10e6,
        data_rate     = RF24_DATA_RATE.RATE_2MBPS,
        channel       = 76,
        payload_size  = RF24_PAYLOAD.DYNAMIC,
        address_bytes = 4,
        crc_bytes     = RF24_CRC.BYTES_2,
        pa_level      = RF24_PA.HIGH,
    )

    address = b"ABCD"
    nrf.open_writing_pipe(address)
    nrf.open_reading_pipe(RF24_RX_ADDR.P1, address)

    disable_auto_ack(nrf)
    
    INFO(f"Radio details:")
    nrf.show_registers()

    return nrf
# :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

# :::: COMPRESSION :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
def compress_zstd(data, level=3) -> bytes:
    try:
        import zstandard as zstd
    except Exception as e:
        raise RuntimeError("The “zstandard” library is not installed. Install it with: pip3 install zstandard") from e
    cctx = zstd.ZstdCompressor(level=level)
    return cctx.compress(data)

def decompress_zstd(data) -> bytes:
    try:
        import zstandard as zstd
    except Exception as e:
        raise RuntimeError("The “zstandard” library is not installed. Install it with: pip3 install zstandard") from e
    dctx = zstd.ZstdDecompressor()
    return dctx.decompress(data)
# :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

# :::: USB IO :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
USB_MOUNT_PATH = Path("/media")

def get_usb_mount_path() -> Path | None:
    """
    Try to find a valid USB device connected to the USB mount path
    """
    
    for path, _, _ in USB_MOUNT_PATH.walk():
        if path.is_mount():
            return path

    return None

def find_valid_txt_file_in_usb(usb_mount_path: Path) -> Path | None:
    """
    Searches for all the txt files in the first level of depth of the USB mount
    location and returns the path to first one ordered alphabetically
    """
    if not usb_mount_path:
        return None
    
    file = [
        file
        for file in usb_mount_path.iterdir()
        if file.is_file()
        and file.suffix == ".txt"
        and not str(file).startswith(".")
    ]

    file = sorted(file)

    if not file:
        return None

    return file[0].resolve()
# :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::


# :::: CHANNELS :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
def is_channel_free(nrf: NRF24) -> int:
    return nrf._nrf_read_reg(NRF24.RPD, 1)[0] & 1

def choose_free_channel(nrf: NRF24, own_channels: list[int]) -> int:
    nrf.power_up_rx()

    INFO("CALLARSE QUE QUIERO ELEGIR UN CANAL PA TRANSMITIR")
    number_of_cycles    = 10
    channel_occupability = [
        0 for _ in own_channels
    ]
    for i in range(number_of_cycles):
        for idx, channel in enumerate(own_channels):
            nrf.set_channel(channel)
            time.sleep(.1)
            channel_occupability[idx] += is_channel_free(nrf)

        if cfg.STATE != cfg.STATE_SEND_ACTIVE:
            raise StateChanged("SEND_ACTIVE")

    selected = own_channels[0]
    n        = number_of_cycles + 1
    for occ, channel in zip(channel_occupability, own_channels):
        if occ < n:
            selected = channel
            n        = occ

        #if cfg.STATE != cfg.STATE_SEND_ACTIVE:
         #   return -1

    INFO(f"POS TRANSMITO EN EL CANAL {selected}")
    INFO(F"LA OKUPABILIDAD DE ESE CANAL ES {n}")
    return selected
            
def choose_occupied_channel(nrf: NRF24, other_channels: list[int], channel_idx) -> tuple[int, int]:
    nrf.power_up_rx()
    cfg.set_state(cfg.STATE_RECV_WAIT)
    #channel_idx = 0
    INFO("CALLARSE QUE ESTOY ESCUCHANDO CANALES")
    while True:
        channel = other_channels[channel_idx % len(other_channels)]
        INFO(f"TOY PROBANDO EN EL CANAL {channel} ")
        tic = time.time()
        tac = time.time()
        while (tac - tic) < channel_read_timeout:
            tac = time.time()
            nrf.set_channel(channel)
            time.sleep(.1)

            if cfg.STATE != cfg.STATE_RECV_WAIT:
                raise StateChanged("RECV_WAIT")

            if not nrf.data_ready(): continue
            
            INFO(f"POS ESCUCHO EN EL CANAL {channel}")
            return channel, channel_idx


        channel_idx += 1
# :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::


# :::: FLOW FUNCTIONS :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
def ACT_AS_TX(nrf: NRF24, content2: bytes, own_channels: list[int]) -> None:
    INFO("SOY UN TRANSMISOR PUTA")
    channel = choose_free_channel(nrf, own_channels)
    nrf.set_channel(channel)

    #if cfg.STATE != cfg.STATE_SEND_ACTIVE:
     #   return -1

    if (len(content2)>CUT_LENGTH):
        length = CUT_LENGTH
    else:
        length = len(content2)
    
    content2 = content2[0:int(length)]

    INFO(f"LEN CONTENT NO COMPRESSION: {len(content2)}")

    content = compress_zstd(content2, ZSTD_LEVEL)

    INFO(f"LEN CONTENT COMPRESSION: {len(content)}")

    # split the bytes into frames with a FrameID
    frames = [
        FrameID.to_bytes(2) + content[i : i + BYTES_IN_FRAME]
        for FrameID, i in enumerate(range(0, len(content), BYTES_IN_FRAME))
    ]

    #max_data = min(2^(8*LENGTH_BYTES), 2^(8*(FRAME_ID_BYTES-1))*31)

    control_message  = bytes()
    control_message += 0xFFFF.to_bytes(2)              # Header reserved to control messages
    control_message += shake_256(content).digest(28) # Checksum of the file
    control_message += len(content).to_bytes(2)      # Ammount of data to transmit
    INFO(f"DATA LEN: {len(content)}")
    INFO(f"CHECKSUM: {shake_256(content).digest(28)}")

    cycle = []
    cycle.append(control_message)
    cycle.extend(frames)

    #INFO(f"Cycle: {cycle}")

    cycle_len = len(cycle)
    INFO(f"Cycle_len {cycle_len}")

    idx = 0

    tic = time.time()
    while True:

        if cfg.STATE != cfg.STATE_SEND_ACTIVE:
            raise StateChanged("SEND_ACTIVE")

        message = cycle[idx % cycle_len]
        #INFO(f"Frame: {message}")
        #INFO(f"FrameID {int.from_bytes(message[0:2])}")
        nrf.send(message)
        idx += 1
        tac = time.time()
        if (tac- tic) > channel_tx_timeout:
            INFO("VOY A CAMBIAR DE CANAL A VER SI HAY OTRO MEJOR")
            channel = choose_free_channel(nrf, own_channels)
            nrf.set_channel(channel)
            tic = time.time()

    return

def ACT_AS_RX(nrf: NRF24, other_channels: list[int]) -> bytes:
    INFO("SOY UN RECEPTOR")
    channel, channel_idx = choose_occupied_channel(nrf, other_channels, 0)
    nrf.set_channel(channel)

    cfg.set_state(cfg.STATE_RECV_ACTIVE)

    checksum           = None
    is_reading_frames  = False
    slot_not_generated = True
    slots              = []

    tries = 0

    tic = time.time()
    
    while True:

        if not nrf.data_ready():
            tac = time.time()
            if (tac- tic) > channel_permanence_timeout:
                INFO("VOY A PROBAR A CAMBIAR DE CANAL PORK ESTE VA TO MAL")
                channel, channel_idx = choose_occupied_channel(nrf, other_channels, channel_idx+1)

                if cfg.STATE != cfg.STATE_RECV_WAIT:
                    raise StateChanged("RECV_WAIT")

                nrf.set_channel(channel)
            continue

        frame: bytes = nrf.get_payload()
        #INFO(f"FRAME_ {frame}")

        frame_id = int.from_bytes(frame[0:2])
        #INFO(f"FRAME ID: {frame_id}")

        if frame_id == 0xFFFF:
            #INFO(f"FRAME ID: {frame_id}")
            _        = frame[0]
            checksum = frame[2:30]
            data_len = int.from_bytes(frame[30:32])
            #INFO(f"DATA LEN: {data_len}")

            num_of_frames = ceil(data_len / BYTES_IN_FRAME)
            #INFO(f"NUM FRAMES:{num_of_frames}")

            if slot_not_generated:
                slots = [
                    bytes()
                    for _ in range(num_of_frames)
                ]

                slot_not_generated = False

            is_reading_frames = True



        if is_reading_frames and (frame_id <= num_of_frames - 1):
            slots[frame_id] = frame[2:]



        if is_reading_frames and (frame_id == num_of_frames - 1):
            computed_checksum = shake_256(b"".join(slots)).digest(28)
            INFO(f"CHECKSUM: {computed_checksum}")

            if computed_checksum == checksum:
                SUCC("EL CHESUM TA TO BIEN PRIMIKO")
                compressed_file = b"".join(slots)
                decompressed_file = decompress_zstd(compressed_file)
                return decompressed_file

            else:
                WARN("EL CHESUM TA MAL LOKO")
                
                tries += 1
                if tries >= PERSEVERANCE:
                    cfg.set_state(cfg.STATE_RECV_WAIT)
                    INFO("VOY A PROBAR A CAMBIAR DE CANAL PORK ESTE VA TO MAL")

                    #if cfg.state != cfg.STATE_RECV_WAIT:
                        #return

                    channel, channel_idx = choose_occupied_channel(nrf, other_channels, channel_idx+1)


                    nrf.set_channel(channel)
                    
        tic = time.time()



def save_file_usb(content: bytes) -> None:
    file_saved = False
    while (file_saved == False):
        usb_mount_path = get_usb_mount_path()
        if usb_mount_path:
            INFO("SE HA ENCONTRADO UN USB PA GUARDAR LAS COSAS ERMANIKO") 
            (usb_mount_path / "file_received.txt").write_bytes(content)
            file_saved = True
            SUCC("ARCHIVO GUARDADO EN EL USB")
            cfg.set_state(cfg.STATE_RECV_USB_DONE)

        if cfg.STATE != cfg.STATE_RECV_WAIT_USB:
            raise StateChanged("RECV_WAIT_USB")
    return
# :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::





# :::: MAIN :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
def main(is_tx=0, is_standalone=0):
    """
    Main flow of the application
    """
    try:
        if is_standalone:
            parser = argparse.ArgumentParser(description="NRF24 Pretest")
            parser.add_argument(
                "--tx",
                action="store_true",      # Si se pone la flag vale True, si no False
                help="Declara el nodo como transmisor",
            )
            args = parser.parse_args()

            is_tx = args.tx

        nrf            = create_radio_object(CE_PIN) 
        cfg.set_state(cfg.STATE_IDLE)
        usb_mount_path = get_usb_mount_path()
        file_path      = find_valid_txt_file_in_usb(usb_mount_path)

        all_channels   = [channel for channel in range(0, 50 + 1, 5)]

        own_channels = all_channels

        other_channels = all_channels

        INFO(f"ALL CHANNELS: {all_channels}")

        content        = None

        if is_tx:
            last_msg = None
            msg = None
            INFO("ESTE NODO HA SIDO ESCOGIDO COMO TX")
            cfg.set_state(cfg.STATE_SEND_WAIT)

            while not file_path:
                if not usb_mount_path:
                    msg = "ESPERANDO A QUE SE INTRODUZCA UN USB..."
                else:
                    msg = "NO SE ENCUENTRA NINGUN ARCHIVO EN EL USB"

                if msg is not None and msg != last_msg:
                    INFO(msg)
                    last_msg = msg
                
                usb_mount_path = get_usb_mount_path()
                file_path      = find_valid_txt_file_in_usb(usb_mount_path)

                if cfg.STATE != cfg.STATE_SEND_WAIT:
                    raise StateChanged("SEND_WAIT")

            INFO("HAY UN USB CON UN ARCHIVO DENTRO")
            INFO(f"SE HA ENCONTRADO EL SIGUIENTE ARCHIVO:{file_path}")
            content = file_path.read_bytes()
            cfg.set_state(cfg.STATE_SEND_ACTIVE)
            ACT_AS_TX(nrf, content, own_channels)

        else:
            INFO("NO HE SIDO ESCOGIDO COMO TX :((")
            content = ACT_AS_RX(nrf, other_channels)
            usb_mount_path = get_usb_mount_path()
            if usb_mount_path:
                INFO("SE HA ENCONTRADO UN USB PA GUARDAR LAS COSAS ERMANIKO") 
                (usb_mount_path / "file_received.txt").write_bytes(content)
                SUCC("ARCHIVO GUARDADO EN EL USB")
                cfg.set_state(cfg.STATE_RECV_USB_DONE)
            else:
                INFO("NO SA ENCONTRAO EL USB PA GUARDAR, LO GUARDO POR AHI")
                Path("file_received.txt").write_bytes(content)
                INFO("BUSCANDO UN USB PARA GUARDAR EL ARCHIVO...")
                cfg.set_state(cfg.STATE_RECV_WAIT_USB)
                save_file_usb(content)

        nrf.power_down()
        
        return
    except StateChanged as e:
        nrf.power_down()
        WARN(f"STATE {e} INTERRUMPTED")
# :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::




if __name__ == "__main__":
    try:
        main(is_standalone=1)
    except KeyboardInterrupt:
        ERROR("Process interrupted by the user")
    finally:
        os.system("sudo killall pigpiod")
