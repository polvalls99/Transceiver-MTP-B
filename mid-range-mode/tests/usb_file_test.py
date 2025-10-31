#!/usr/bin/env python3
"""
usb_file_test.py

Prueba la lectura y escritura en disco (por ejemplo un USB) usando la misma
lógica de chunking usada en quick-mode-sender/receiver.py.

Uso:
    python usb_file_test.py send <ruta_fichero_origen> <ruta_destino_simulado>
    python usb_file_test.py recv <ruta_fichero_simulado> <ruta_fichero_guardado>
    python usb_file_test.py roundtrip <ruta_origen_usb> <ruta_destino_usb>

- send:    lee el fichero (rb) y crea un "stream" de chunks en memoria (simula envío).
- recv:    lee el "stream" de chunks y escribe en disco (wb) (simula recepción).
- roundtrip: combina ambos pasos: lee desde origen, escribe en destino y verifica.
"""

import argparse
import os
import sys

CHUNK_SIZE = 32

def read_file_in_chunks(filepath):
    """Lee fichero en binario y devuelve lista de chunks (simula sender)."""
    print(f"Reading file: {filepath}")
    with open(filepath, 'rb') as f:
        data = f.read()
    size = len(data)
    print(f"Read {size} bytes.")
    chunks = [data[i:i+CHUNK_SIZE] for i in range(0, size, CHUNK_SIZE)]
    return chunks, size

def write_chunks_to_file(chunks, output_filepath):
    """Escribe chunks en un fichero en binario (simula receiver)."""
    print(f"Writing to: {output_filepath}")
    os.makedirs(os.path.dirname(output_filepath) or '.', exist_ok=True)
    bytes_written = 0
    with open(output_filepath, 'wb') as f:
        for i, chunk in enumerate(chunks, start=1):
            # En el código NRF, un payload vacío señalaba EOF; aquí no lo necesitamos,
            # pero seguimos la lógica de escribir cada chunk.
            f.write(chunk)
            bytes_written += len(chunk)
            # Barra de progreso sencilla (por chunk, no por bytes totales)
            # (si el tamaño total fuera conocido, podríamos hacer porcentaje)
            print(f"Chunks written: {i}  (total bytes: {bytes_written})", end='\r')
    print()  # salto de línea
    print(f"Finished writing. Total bytes: {bytes_written}")
    return bytes_written

def show_progress_bar(current, total, prefix='Progress', length=50):
    if total == 0:
        pct = 100.0
    else:
        pct = (current * 100) / total
    filled_len = int(length * pct // 100)
    bar = '█' * filled_len + '-' * (length - filled_len)
    print(f'{prefix}: |{bar}| {pct:6.2f}%   ', end='\r')

def send_mode(src, dst_simulated):
    """Simula el comportamiento del sender: lee y guarda 'stream' intermedio en un fichero .chunks"""
    chunks, total_bytes = read_file_in_chunks(src)
    # Guardamos los chunks en un fichero intermedio para simular el paso por radio/USB
    inter_path = dst_simulated
    print(f"Saving simulated stream to: {inter_path}")
    with open(inter_path, 'wb') as f:
        chunks_sent = 0
        for chunk in chunks:
            # Escribimos cada chunk tal cual (en el mundo NRF se transmitía)
            f.write(chunk)
            chunks_sent += 1
            show_progress_bar(chunks_sent * CHUNK_SIZE, total_bytes, prefix='Sending')
    # Escribir EOF como paquete vacío (opcional). Aquí no añade bytes.
    # f.write(b'')  # no cambia nada en fichero
    print()
    print(f"Simulated send complete. Chunks: {chunks_sent}, bytes: {total_bytes}")
    return inter_path, total_bytes

def recv_mode(simulated_stream_path, output_filepath):
    """Simula el receiver leyendo el stream intermedio y guardando en output_filepath"""
    print(f"Reading simulated stream from: {simulated_stream_path}")
    with open(simulated_stream_path, 'rb') as f:
        data = f.read()
    # dividir en chunks como lo haría get_payload()
    chunks = [data[i:i+CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]
    total_bytes = len(data)
    print(f"Simulated stream size: {total_bytes} bytes, chunks: {len(chunks)}")
    # Escritura final
    bytes_written = write_chunks_to_file(chunks, output_filepath)
    return bytes_written

def roundtrip_mode(src, dst):
    """Lee src (USB), simula envío/recepción y escribe dst (USB). Finalmente verifica."""
    # Paso 1: leer y crear stream simulado en memoria (no fichero intermedio)
    chunks, total_bytes = read_file_in_chunks(src)
    # Mostrar envío
    for i in range(1, len(chunks)+1):
        show_progress_bar(i * CHUNK_SIZE, total_bytes, prefix='Sending')
    print()
    # Paso 2: receptor escribe fichero
    bytes_written = write_chunks_to_file(chunks, dst)
    # Paso 3: verificar
    same = False
    if bytes_written == total_bytes:
        # comparar contenidos
        with open(src, 'rb') as f1, open(dst, 'rb') as f2:
            same = (f1.read() == f2.read())
    print("Verification:", "OK - files identical" if same else "MISMATCH")
    return same

def guess_path_description(path):
    # Solo ayuda rápida para el usuario
    if path.startswith('/media') or path.startswith('/run/media') or path.startswith('/mnt'):
        return "posible montaje USB en Linux"
    if os.path.splitdrive(path)[0]:
        return "posible unidad en Windows"
    return "ruta de fichero"

def main():
    parser = argparse.ArgumentParser(description="Prueba lectura/escritura tipo NRF24 sobre ficheros (simulado).")
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_send = sub.add_parser('send', help='Leer fichero y guardar stream simulado en un fichero')
    p_send.add_argument('source', help='Fichero de origen (ej. /media/usbdisk/mi.txt)')
    p_send.add_argument('simulated_stream', help='Fichero donde guardar el stream simulado (ej. /tmp/stream.bin)')

    p_recv = sub.add_parser('recv', help='Leer stream simulado y escribir fichero de salida')
    p_recv.add_argument('simulated_stream', help='Fichero stream simulado (ej. /tmp/stream.bin)')
    p_recv.add_argument('output', help='Fichero de salida (ej. /media/usbdisk/recibido.txt)')

    p_rt = sub.add_parser('roundtrip', help='Leer desde origen y escribir destino y verificar')
    p_rt.add_argument('source', help='Fichero origen (ej. /media/usbdisk/mi.txt)')
    p_rt.add_argument('dest', help='Fichero destino (ej. /media/usbdisk/mi_copy.txt)')

    args = parser.parse_args()

    if args.cmd == 'send':
        print(f"Source ({guess_path_description(args.source)}): {args.source}")
        print(f"Simulated stream path: {args.simulated_stream}")
        send_mode(args.source, args.simulated_stream)

    elif args.cmd == 'recv':
        print(f"Simulated stream path: {args.simulated_stream}")
        print(f"Output ({guess_path_description(args.output)}): {args.output}")
        recv_mode(args.simulated_stream, args.output)

    elif args.cmd == 'roundtrip':
        print(f"Source ({guess_path_description(args.source)}): {args.source}")
        print(f"Dest ({guess_path_description(args.dest)}): {args.dest}")
        ok = roundtrip_mode(args.source, args.dest)
        if ok:
            print("Roundtrip OK. El fichero se ha copiado correctamente.")
        else:
            print("Roundtrip fallido. Comprueba permisos/rutas y vuelve a intentarlo.")
            sys.exit(2)

if __name__ == "__main__":
    main()
