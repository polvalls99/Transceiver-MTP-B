#!/usr/bin/env python3
"""
Quick Mode Auto Sender (MODIFICADO PARA REINTENTO INFINITO)
- Divide el .txt en N_CHUNKS trozos.
- Comprime (zstd) y calcula el MD5 de CADA trozo por separado.
- Envía cada trozo como un paquete independiente con su propio header.
- El header incluye {'chunk_index': i, 'chunk_total': N, ...}
- Si la conexión se corta (TimeoutError), reintenta el envío
  del MISMO paquete indefinidamente, alternando 1/2 Mbps.
"""
import argparse, sys, time, json, os, hashlib, traceback
import pigpio
from nrf24 import *

HEADER_TERMINATOR = b'\n\n'
CHUNK_SIZE = 32
POLL_INTERVAL = 1.0
ZSTD_LEVEL = 3 
N_CHUNKS = 3

def find_usb_mounts():
    mounts = []
    try:
        with open('/proc/mounts','r') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    m = parts[1]
                    if m.startswith('/media/') or m.startswith('/mnt/'):
                        mounts.append(m)
    except Exception: pass
    return mounts

def find_most_recent_txt(m):
    cands = []
    for root, _, files in os.walk(m):
        for fn in files:
            if fn.lower().endswith('.txt'):
                full = os.path.join(root, fn)
                try:
                    cands.append((os.path.getmtime(full), full))
                except Exception: pass
    if not cands: return None
    cands.sort(reverse=True)
    return cands[0][1]

def wait_for_usb_and_get_txt():
    print("Waiting for a USB drive containing a .txt file...")
    while True:
        mounts = find_usb_mounts()
        if mounts:
            for m in mounts:
                c = find_most_recent_txt(m)
                if c:
                    print(f"Found .txt on {m}: {c}")
                    return c, m
        time.sleep(POLL_INTERVAL)

def wait_for_unplug(m):
    print(f"Waiting for {m} to be removed to reset...")
    while True:
        if m not in find_usb_mounts(): print(f"{m} removed."); return
        time.sleep(POLL_INTERVAL)

def md5sum(b):
    h = hashlib.md5(); h.update(b); return h.hexdigest()

def compress_zstd(data_bytes, level=ZSTD_LEVEL):
    try:
        import zstandard as zstd
    except Exception as e:
        raise RuntimeError("The “zstandard” library is not installed. Install it with: pip3 install zstandard") from e
    cctx = zstd.ZstdCompressor(level=level)
    return cctx.compress(data_bytes)


# --- ESTA ES LA FUNCIÓN MODIFICADA ---
def _send_chunk_robust(nrf, header_obj, compressed_data):
    """
    Función helper para enviar un único trozo (header + datos)
    con la lógica de REINTENTO INFINITO por paquete.
    """
    header = json.dumps(header_obj).encode('utf-8') + HEADER_TERMINATOR
    compressed_size = len(compressed_data)
    
    print(f"Sending Chunk {header_obj['chunk_index']+1}/{header_obj['chunk_total']}: {header_obj}")

    sent_bytes = 0; header_pos = 0; data_pos = 0
    state = 2  # 2=2Mbps, 1=1Mbps

    # Configuración inicial
    nrf.set_data_rate(RF24_DATA_RATE.RATE_2MBPS)
    nrf.flush_tx()
    nrf.flush_rx()
    state = 2

    # Bucle exterior: itera sobre los datos y obtiene el *siguiente* paquete
    while True:
        
        # 1. Determinar el paquete de 32 bytes que se debe enviar
        if header_pos + CHUNK_SIZE <= len(header):
            packet_to_send = header[header_pos:header_pos+CHUNK_SIZE]
            is_header = True; is_data = False; data_len = 0
        elif header_pos < len(header):
            rem = header[header_pos:]; need = CHUNK_SIZE - len(rem)
            fill = compressed_data[data_pos:data_pos+need]
            packet_to_send = rem + fill
            is_header = True; is_data = True; data_len = len(fill)
        elif sent_bytes < compressed_size:
            packet_to_send = compressed_data[data_pos:data_pos+CHUNK_SIZE]
            if not packet_to_send: break # No hay más datos
            is_header = False; is_data = True; data_len = len(packet_to_send)
        else:
            break # Envío de este trozo completado

        # 2. Bucle interior: reintenta el envío de ESE paquete hasta tener éxito
        while True:
            try:
                nrf.send(packet_to_send)
                nrf.wait_until_sent()
                
                # --- ÉXITO ---
                # El paquete se envió. Salir del bucle de reintento.
                break 
            
            except TimeoutError:
                # --- FALLO (PAPEL DE PLATA) ---
                # El paquete no se envió. Gestionar bloqueo.
                nrf.flush_tx() # Limpiar buffer
                
                if state == 2:
                    print("\n[Timeout 2Mbps] -> Retrying same packet at 1 Mbps...")
                    nrf.set_data_rate(RF24_DATA_RATE.RATE_1MBPS)
                    state = 1
                else: # state == 1
                    print("\n[Timeout 1Mbps] -> Retrying same packet at 2 Mbps after 1s pause...")
                    time.sleep(1.0) # Pausa antes de volver a la alta velocidad
                    nrf.set_data_rate(RF24_DATA_RATE.RATE_2MBPS)
                    state = 2
                
                # NO salimos del bucle. 'continue' es implícito.
                # Volveremos a ejecutar el 'try' con la nueva configuración
                # para enviar el MISMO 'packet_to_send'.

        # 3. Actualizar contadores (solo si el envío tuvo éxito)
        if is_header and not is_data:
            header_pos += CHUNK_SIZE
        elif is_header and is_data:
            header_pos = len(header) # Marcar header como enviado
            data_pos += data_len
            sent_bytes += data_len
        elif is_data:
            data_pos += data_len
            sent_bytes += data_len
        
        print(f"Chunk Progress: {sent_bytes}/{compressed_size} bytes ({100*sent_bytes/max(1,compressed_size):.1f}%)", end='\r')

    print(f"\nChunk {header_obj['chunk_index']+1}/{header_obj['chunk_total']} transfer complete.")
# --- FIN DE LA FUNCIÓN MODIFICADA ---


def send_file(pi, nrf, path, address):
    print(f"Reading file: {path}")
    try:
        with open(path,'rb') as f: data = f.read()
        lines = data.splitlines(True) # Mantiene los \n
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    if not lines:
        print("File is empty, nothing to send.")
        return

    # --- LÓGICA DE DIVISIÓN EN TROZOS (CHUNKS) ---
    chunk_size_lines = (len(lines) + N_CHUNKS - 1) // N_CHUNKS
    line_chunks = []
    for i in range(N_CHUNKS):
        start = i * chunk_size_lines
        end = min((i + 1) * chunk_size_lines, len(lines))
        if start < end:
            line_chunks.append(lines[start:end])
    
    actual_n_chunks = len(line_chunks)
    print(f"File split into {actual_n_chunks} chunks.")
    
    filename = os.path.basename(path)

    # --- BUCLE DE ENVÍO DE TROZOS ---
    for i, chunk_lines in enumerate(line_chunks):
        try:
            # 1. Preparar datos del trozo
            original_chunk_data = b''.join(chunk_lines)
            orig_size = len(original_chunk_data)
            orig_md5 = md5sum(original_chunk_data)
            
            # 2. Comprimir trozo
            compressed_data = compress_zstd(original_chunk_data, level=ZSTD_LEVEL)
            compressed_size = len(compressed_data)

            # 3. Crear header del trozo
            header_obj = {
                'filename': filename,
                'chunk_index': i,
                'chunk_total': actual_n_chunks,
                'size': compressed_size,
                'md5': orig_md5,
                'orig_size': orig_size,
                'compression': "zstd"
            }

            # 4. Enviar trozo con lógica robusta
            _send_chunk_robust(nrf, header_obj, compressed_data)
            
            time.sleep(0.1) # Pausa entre trozos

        except Exception as e:
            # Esta excepción ahora solo debería saltar si _send_chunk_robust
            # falla por algo que NO es un TimeoutError (ej. error de pigpio)
            print(f"\n---!! CRITICAL FAILURE on CHUNK {i+1}/{actual_n_chunks}: {e} !!---")
            traceback.print_exc()
            print(f"Skipping to next chunk...")

    print("All chunks sent.")


def main():
    p = argparse.ArgumentParser(description="NRF24 Auto File Sender (Chunked, Robust) + IRQ + Zstd")
    p.add_argument('-n','--hostname', default='localhost')
    p.add_argument('-p','--port', type=int, default=8888)
    p.add_argument('--irq', type=int, default=24, help="GPIO IRQ para PUD_UP. Usa -1 para omitir.")
    p.add_argument('address', nargs='?', default='FILEX')
    args = p.parse_args()

    print(f"Connecting pigpio {args.hostname}:{args.port}")
    pi = pigpio.pi(args.hostname, args.port)
    if not pi.connected:
        print("pigpio not connected"); sys.exit(1)

    if args.irq >= 0:
        try:
            pi.set_mode(args.irq, pigpio.INPUT)
            pi.set_pull_up_down(args.irq, pigpio.PUD_UP)
            print(f"IRQ line pull-up on GPIO{args.irq}")
        except Exception as e:
            print(f"IRQ GPIO setup failed: {e}")

    nrf = NRF24(pi, ce=25, payload_size=CHUNK_SIZE, channel=100,
                data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN, spi_speed=10e6)
    nrf.set_address_bytes(len(args.address))
    nrf.set_retransmission(15, 15) # Esto ya da 15 reintentos de hardware por CADA send()
    nrf.open_writing_pipe(args.address)
    nrf.show_registers()

    try:
        while True:
            try:
                txt_path, mnt = wait_for_usb_and_get_txt()
                try:
                    send_file(pi, nrf, txt_path, args.address)
                except Exception:
                    traceback.print_exc()
                    print("Error during transmission. Waiting for next removal/insert.")
                wait_for_unplug(mnt)
            except KeyboardInterrupt:
                print("\nUser interrupted."); break
    finally:
        nrf.power_down(); pi.stop()

if __name__ == "__main__":
    main()