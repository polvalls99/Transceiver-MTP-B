#!/usr/bin/env python3
"""
Quick Mode Auto Receiver with IRQ support (MODIFICADO PARA TROZOS v2)
- Recibe trozos independientes (chunk_index, size, md5)
- Verifica el MD5 de CADA trozo tras descomprimirlo.
- Guarda los trozos verificados en la SD LOCAL ('output_dir') como 'filename.part_X'
- SONDEA la inserción de un nuevo USB.
- Al detectar un NUEVO USB, ensambla las partes desde la SD
  directamente al USB, y luego BORRA las partes de la SD.
"""
import argparse, sys, time, json, os, hashlib, traceback, shutil, threading
import re
import pigpio
from nrf24 import *

HEADER_TERMINATOR = b'\n\n'
CHUNK_SIZE = 32
USB_POLL_INTERVAL = 1.0 # Segundos entre cada sondeo de USB

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
    except Exception:
        pass
    return mounts

def compute_md5_bytes(b):
    h = hashlib.md5(); h.update(b); return h.hexdigest()

def decompress_zstd(data_bytes):
    try:
        import zstandard as zstd
    except Exception as e:
        raise RuntimeError("The “zstandard” library is not installed. Install it with: pip3 install zstandard") from e
    dctx = zstd.ZstdDecompressor()
    return dctx.decompress(data_bytes)

def clear_directory(d):
    """Limpia el directorio, PERO ignora los .part_X existentes si reinicias."""
    if not os.path.isdir(d): return
    for n in os.listdir(d):
        if re.search(r'\.part_\d+$', n):
            print(f"Found existing part file, skipping: {n}")
            continue
        p = os.path.join(d, n)
        try:
            if os.path.islink(p) or os.path.isfile(p): os.remove(p)
            elif os.path.isdir(p): shutil.rmtree(p)
        except Exception: pass

def assemble_to_usb(local_output_dir, usb_mount_path):
    """
    Ensambla todos los ficheros .part_X encontrados en 'local_output_dir',
    los escribe en el 'usb_mount_path' y borra las partes locales.
    """
    print(f"\n--- Assembling files from {local_output_dir} to {usb_mount_path} ---")
    files_to_assemble = {} # clave: basename, valor: lista de (index, path_part)
    
    # 1. Encontrar todas las partes en el directorio LOCAL
    try:
        for fname in os.listdir(local_output_dir):
            m = re.match(r'^(.*)\.part_(\d+)$', fname)
            if m:
                basename = m.group(1)
                index = int(m.group(2))
                part_path = os.path.join(local_output_dir, fname)
                if basename not in files_to_assemble:
                    files_to_assemble[basename] = []
                files_to_assemble[basename].append((index, part_path))
    except Exception as e:
        print(f"Error scanning local parts directory: {e}")
        return # No se puede continuar

    if not files_to_assemble:
        print("No part files found to assemble.")
        return

    # 2. Crear directorio de destino en el USB
    usb_dest_dir = os.path.join(usb_mount_path, 'received_files')
    try:
        os.makedirs(usb_dest_dir, exist_ok=True)
    except Exception as e:
        print(f"---!! FAILED to create directory on USB: {usb_dest_dir} ({e}) !!---")
        print("Assembly aborted. Parts remain on local SD card.")
        return

    # 3. Ensamblar cada fichero base
    for basename, parts_list in files_to_assemble.items():
        # Ordenar por índice
        parts_list.sort()
        
        final_usb_path = os.path.join(usb_dest_dir, basename)
        print(f"Assembling {len(parts_list)} parts into: {final_usb_path}")
        
        try:
            with open(final_usb_path, 'wb') as f_out:
                for index, part_path in parts_list:
                    print(f"  > Appending part {index} ({part_path})")
                    with open(part_path, 'rb') as f_in:
                        f_out.write(f_in.read())
            
            print(f"Assembly for {basename} complete. Deleting local parts...")
            for index, part_path in parts_list:
                try:
                    os.remove(part_path)
                except Exception as e:
                    print(f"Warning: could not delete part {part_path}: {e}")
            
            print(f"Successfully assembled and saved to: {final_usb_path}")

        except Exception as e:
            print(f"---!! FAILED to assemble {basename} to USB: {e} !!---")
            traceback.print_exc()
            print("Original parts remain on local SD card.")
    
    print("--- Assembly process finished ---")


def main():
    p = argparse.ArgumentParser(description="NRF24 Auto File Receiver (Chunked, USB Trigger) + IRQ + Zstd")
    p.add_argument('-n','--hostname', default='localhost')
    p.add_argument('-p','--port', type=int, default=8888)
    p.add_argument('--irq', type=int, default=24, help="GPIO IRQ activo en bajo. Usa -1 para desactivar.")
    p.add_argument('address', nargs='?', default='FILEX')
    p.add_argument('output_dir', nargs='?', default='received_files', help="Directorio LOCAL (SD) para guardar partes")
    args = p.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    clear_directory(args.output_dir) # Limpia, pero respeta .part_X
    print(f"Session storage ready: {args.output_dir} (local SD card)")

    print(f"Connecting pigpio {args.hostname}:{args.port}")
    pi = pigpio.pi(args.hostname, args.port)
    if not pi.connected:
        print("pigpio not connected"); sys.exit(1)

    # --- Configuración IRQ (sin cambios) ---
    rx_event = None
    irq_cb = None
    if args.irq >= 0:
        try:
            pi.set_mode(args.irq, pigpio.INPUT)
            pi.set_pull_up_down(args.irq, pigpio.PUD_UP)
            rx_event = threading.Event()
            def _irq_cb(gpio, level, tick):
                if level == 0: rx_event.set()
            irq_cb = pi.callback(args.irq, pigpio.FALLING_EDGE, _irq_cb)
            print(f"IRQ enabled on GPIO{args.irq}")
        except Exception as e:
            print(f"IRQ setup failed: {e}. Using polling.")
            rx_event = None
            try:
                if irq_cb: irq_cb.cancel()
            except Exception: pass
            irq_cb = None
    else:
        print("IRQ disabled. Polling mode.")

    nrf = NRF24(pi, ce=25, payload_size=CHUNK_SIZE, channel=100,
                data_rate=RF24_DATA_RATE.RATE_2MBPS, pa_level=RF24_PA.MIN, spi_speed=10e6)
    nrf.set_address_bytes(len(args.address))
    nrf.open_reading_pipe(RF24_RX_ADDR.P1, args.address)
    nrf.show_registers()

    # --- Variables de estado de recepción (por trozo) ---
    header_buf = bytearray()
    receiving = False
    expected_size = None
    file_bytes = bytearray()
    current_header = {}

    # --- Variables de estado del USB ---
    known_mounts = set(find_usb_mounts())
    last_usb_check = 0.0
    assembly_lock = threading.Lock() # Para evitar ensamblar dos veces

    print("\n--- ¡IMPORTANTE! ---")
    if known_mounts:
        print(f"ADVERTENCIA: USB ya detectado en {known_mounts}")
        print("El ensamblaje automático podría no dispararse. Por favor, reinicie sin el USB conectado.")
    else:
        print("Inicie la recepción. Inserte el USB al final para disparar el ensamblaje.")
    print("--------------------\n")


    def reset_state():
        """Función helper para limpiar el estado después de un trozo."""
        nonlocal header_buf, receiving, expected_size, file_bytes, current_header
        header_buf = bytearray()
        receiving = False
        expected_size = None
        file_bytes = bytearray()
        current_header = {}

    def process_payload(payload):
        nonlocal header_buf, receiving, expected_size, file_bytes, current_header
        
        if not receiving:
            header_buf.extend(payload)
            idx = header_buf.find(HEADER_TERMINATOR)
            if idx != -1:
                header_bytes = header_buf[:idx]
                rest = header_buf[idx+len(HEADER_TERMINATOR):]
                try:
                    h = json.loads(header_bytes.decode('utf-8'))
                    if 'chunk_index' not in h or 'filename' not in h:
                        print(f"Header inválido (no es un trozo), descartando: {h}")
                        reset_state(); return
                    
                    current_header = h
                    expected_size = int(h.get('size',0))
                    print(f"\nHeader chunk {h['chunk_index']+1}/{h['chunk_total']} parsed: "
                          f"filename={h['filename']}, size={expected_size}, md5={h['md5']}")
                    
                except Exception as e:
                    print(f"Header parse error. Reset. {e}")
                    reset_state(); return

                receiving = True
                if rest:
                    take = min(len(rest), expected_size)
                    file_bytes.extend(rest[:take])
                    print(f"Received {len(file_bytes)}/{expected_size} bytes...", end='\r')
        else:
            remaining = expected_size - len(file_bytes)
            if remaining > 0:
                take = min(len(payload), remaining)
                file_bytes.extend(payload[:take])
                print(f"Received {len(file_bytes)}/{expected_size} bytes...", end='\r')

        # --- TROZO RECIBIDO ---
        if receiving and expected_size is not None and len(file_bytes) >= expected_size:
            print(f"\nChunk {current_header['chunk_index']+1} expected bytes reached ({expected_size}). Processing...")
            
            md5_expected = current_header.get('md5')
            filename = current_header.get('filename')
            chunk_index = current_header.get('chunk_index')
            compression = current_header.get('compression')
            
            try:
                # 1. Descomprimir
                if compression == "zstd":
                    decompressed_bytes = decompress_zstd(bytes(file_bytes))
                else:
                    decompressed_bytes = bytes(file_bytes)
                
                # 2. Verificar MD5
                md5_actual = compute_md5_bytes(decompressed_bytes)
                
                if md5_expected and md5_actual == md5_expected:
                    print(f"Chunk MD5 OK: {md5_actual}")
                    
                    # 3. Guardar como .part_X en la SD LOCAL
                    os.makedirs(args.output_dir, exist_ok=True)
                    part_filename = f"{filename}.part_{chunk_index}"
                    save_path = os.path.join(args.output_dir, part_filename)
                    
                    with open(save_path,'wb') as f: f.write(decompressed_bytes)
                    print(f"Saved verified chunk to LOCAL SD: {save_path}")
                    
                else:
                    print(f"---!! CHUNK MD5 MISMATCH !!--- (Chunk {chunk_index+1})")
                    print(f"  Expected: {md5_expected}, Got: {md5_actual}")
                    print(f"  Discarding chunk.")

            except Exception as e:
                print(f"Failed to process/decompress chunk: {e}")
                traceback.print_exc()

            # 4. Resetear estado para el próximo trozo
            reset_state()
            
    # --- Bucle principal ---
    try:
        print(f"Listening on address: {args.address}")
        while True:
            # --- Lógica de recepción de radio (prioridad alta) ---
            if rx_event is not None:
                if rx_event.wait(0.01): # Timeout corto para no bloquear el sondeo USB
                    rx_event.clear()
                    while nrf.data_ready():
                        payload = nrf.get_payload()
                        process_payload(payload)
            else:
                if nrf.data_ready():
                    payload = nrf.get_payload()
                    process_payload(payload)
                else:
                    time.sleep(0.01) # Polling de radio

            # --- Lógica de sondeo USB (prioridad baja) ---
            now = time.time()
            if now - last_usb_check > USB_POLL_INTERVAL:
                last_usb_check = now
                
                current_mounts = set(find_usb_mounts())
                new_mounts = current_mounts - known_mounts
                
                if new_mounts:
                    if assembly_lock.acquire(blocking=False): # No bloquear si ya está ensamblando
                        try:
                            # Solo nos importa el primer USB nuevo que se inserte
                            new_usb_path = list(new_mounts)[0]
                            print(f"\n*** NUEVO USB DETECTADO: {new_usb_path} ***")
                            print("Disparando ensamblaje de partes locales a USB...")
                            
                            # Llamar a la función de ensamblaje
                            assemble_to_usb(args.output_dir, new_usb_path)
                            
                            # Añadir todos los nuevos mounts a la lista de conocidos
                            known_mounts.update(new_mounts)
                            print("Ensamblaje finalizado. Volviendo a la escucha.")
                        except Exception as e:
                            print(f"Error durante el ensamblaje por USB: {e}")
                        finally:
                            assembly_lock.release()
                    else:
                        print("USB detectado, pero el ensamblaje ya está en progreso.")
                                    
    except KeyboardInterrupt:
        print("\nUser interrupted.")
    except Exception:
        traceback.print_exc()
    finally:
        # Limpieza de hardware
        print("\nScript stopping. Cleaning up hardware (IRQ, NRF, pigpio)...")
        try:
            if irq_cb is not None: irq_cb.cancel()
        except Exception: pass
        try:
            nrf.power_down()
        except Exception: pass
        try:
            pi.stop()
        except Exception: pass
        print("Cleanup complete. Exiting.")
        print("NOTA: Si hay partes no ensambladas, están en '{args.output_dir}'.")

if __name__ == "__main__":
    main()