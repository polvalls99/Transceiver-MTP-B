#
#| Fichero                  | Propósito                                        | Codificación | Salto de línea | Emula sistema / Caso de uso                         |
#| ------------------------ | ------------------------------------------------ | ------------ | -------------- | --------------------------------------------------- |
#| `test_utf8_lf.txt`       | Texto multilingüe + símbolos + emoji             | UTF-8        | LF             | **Linux / macOS actual**                            |
#| `test_utf8_crlf.txt`     | Igual al anterior pero con saltos de línea CRLF  | UTF-8        | CRLF           | **Windows**                                         |
#| `test_utf16le.txt`       | Texto multilingüe codificado en UTF-16 LE + BOM  | UTF-16       | LF             | Común en **Windows apps Unicode**                   |
#| `test_latin1.txt`        | Texto extendido limitado al repertorio Latin-1   | Latin-1      | LF             | Típico de **Linux/Unix antiguos o ficheros ISO**    |
#| `test_control_chars.txt` | Caracteres de control, bytes no imprimibles, ANSI y aleatorios | UTF-8 (binario mixto) | N/A (mezclado) | **Prueba de robustez binaria / compatibilidad raw** |

#!/usr/bin/env python3
"""
usb_file_test.py

Genera ficheros de prueba (~100 kB) con distintos saltos de línea y codificaciones,
incluyendo un fichero extra con caracteres de control y bytes no imprimibles.
Permite probar lectura/escritura en disco (simulada) y verificar roundtrip.
"""

import argparse
import os
import sys
import time
import random

CHUNK_SIZE = 32
TARGET_SIZE = 100 * 1024  # ≈100 kB


def read_file_in_chunks(filepath):
    print(f"Reading file: {filepath}")
    with open(filepath, 'rb') as f:
        data = f.read()
    size = len(data)
    print(f"Read {size} bytes.")
    chunks = [data[i:i + CHUNK_SIZE] for i in range(0, size, CHUNK_SIZE)]
    return chunks, size


def write_chunks_to_file(chunks, output_filepath):
    print(f"Writing to: {output_filepath}")
    os.makedirs(os.path.dirname(output_filepath) or '.', exist_ok=True)
    bytes_written = 0
    with open(output_filepath, 'wb') as f:
        for i, chunk in enumerate(chunks, start=1):
            f.write(chunk)
            bytes_written += len(chunk)
            print(f"Chunks written: {i}  (total bytes: {bytes_written})", end='\r')
    print()
    print(f"Finished writing. Total bytes: {bytes_written}")
    return bytes_written


def show_progress_bar(current, total, prefix='Progress', length=50):
    pct = 100.0 if total == 0 else (current * 100) / total
    filled_len = int(length * pct // 100)
    bar = '█' * filled_len + '-' * (length - filled_len)
    print(f'{prefix}: |{bar}| {pct:6.2f}%   ', end='\r')


def send_mode(src, dst_simulated):
    chunks, total_bytes = read_file_in_chunks(src)
    inter_path = dst_simulated
    print(f"Saving simulated stream to: {inter_path}")
    with open(inter_path, 'wb') as f:
        chunks_sent = 0
        for chunk in chunks:
            f.write(chunk)
            chunks_sent += 1
            show_progress_bar(chunks_sent * CHUNK_SIZE, total_bytes, prefix='Sending')
    print()
    print(f"Simulated send complete. Chunks: {chunks_sent}, bytes: {total_bytes}")
    return inter_path, total_bytes


def recv_mode(simulated_stream_path, output_filepath):
    print(f"Reading simulated stream from: {simulated_stream_path}")
    with open(simulated_stream_path, 'rb') as f:
        data = f.read()
    chunks = [data[i:i + CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]
    total_bytes = len(data)
    print(f"Simulated stream size: {total_bytes} bytes, chunks: {len(chunks)}")
    bytes_written = write_chunks_to_file(chunks, output_filepath)
    return bytes_written


def roundtrip_mode(src, dst):
    chunks, total_bytes = read_file_in_chunks(src)
    for i in range(1, len(chunks) + 1):
        show_progress_bar(i * CHUNK_SIZE, total_bytes, prefix='Sending')
    print()
    bytes_written = write_chunks_to_file(chunks, dst)
    same = False
    if bytes_written == total_bytes:
        with open(src, 'rb') as f1, open(dst, 'rb') as f2:
            same = (f1.read() == f2.read())
    print("Verification:", "OK - files identical" if same else "MISMATCH")
    return same


def guess_path_description(path):
    if path.startswith('/media') or path.startswith('/run/media') or path.startswith('/mnt'):
        return "posible montaje USB en Linux"
    if os.path.splitdrive(path)[0]:
        return "posible unidad en Windows"
    return "ruta de fichero"


# ------------------ GENERAR FICHEROS DE PRUEBA Y RUN_ALL ------------------

def _repeat_to_target(data: bytes, target_size: int) -> bytes:
    if not data:
        return b''
    times = (target_size // len(data)) + 1
    repeated = (data * times)[:target_size]
    return repeated


def generate_tests():
    """Genera 5 ficheros de prueba (~100 kB cada uno)."""

    multilingual = (
        "Latin: a á à â ä å æ œ ñ  ß  ç\n"
        "Greek: α β γ δ ε ζ η θ ι κ λ μ ν ξ ο π ρ σ τ υ φ χ ψ ω\n"
        "Cyrillic: А Б В Г Д Е Ж З И Й К Л М Н О П Р С Т У Ф Х Ц Ч Ш Щ\n"
        "Arabic: العربية العربية\n"
        "Hebrew: עברית עברית\n"
        "Devanagari: हिन्दी भाषा का एक वाक्य\n"
        "Chinese: 中文漢字 例子\n"
        "Japanese: 日本語の例文\n"
        "Korean: 한국어 예문\n"
        "Emoji: 😀 😃 😄 😁 😆 🚀 🌍 🔥 🧪 🧠\n"
        "Symbols: © ® ™ ✓ ± ÷ × ¼ ½ ¾ ∞ ∑ ∫ √ π\n"
        "Currency: € £ ¥ ₹ $ ₩ ฿\n"
        "Accents: Š Đ Ć Ž č ć ž\n"
        "Arrows: ← ↑ → ↓ ↔ ↕ ↖ ↗ ↘ ↙\n"
        "Combining: é ô å (composed and combining)\n"
        "Misc: ¶ • ◦ ♦ ♣ ♥ ♠ ★ ☆ ⚑ ⚙\n"
    )
    extra = "\u200d\u200c\u2060"

    # UTF-8 con LF
    fn_utf8_lf = "test_utf8_lf.txt"
    sample_utf8 = (multilingual + extra + "\n").encode('utf-8')
    with open(fn_utf8_lf, 'wb') as f:
        f.write(_repeat_to_target(sample_utf8, TARGET_SIZE))

    # UTF-8 con CRLF (Windows)
    fn_utf8_crlf = "test_utf8_crlf.txt"
    text_crlf = multilingual.replace("\n", "\r\n") + extra + "\r\n"
    sample_utf8_crlf = text_crlf.encode('utf-8')
    with open(fn_utf8_crlf, 'wb') as f:
        f.write(_repeat_to_target(sample_utf8_crlf, TARGET_SIZE))

    # UTF-16 LE con BOM
    fn_utf16le = "test_utf16le.txt"
    sample_utf16le = (multilingual + extra + "\n").encode('utf-16le')
    with open(fn_utf16le, 'wb') as f:
        f.write(b'\xff\xfe' + _repeat_to_target(sample_utf16le, TARGET_SIZE))

    # Latin-1 / Windows-1252
    fn_latin1 = "test_latin1.txt"
    latin1_text = (
        "Latin-1: a á à â ä å æ œ ñ ß ç ¡ ¿ © ® ª º\n"
        "Symbols: £ € ¥ ¢ µ\n"
        "Accents: È É Ê Ë Ì Í Î Ï Ò Ó Ô Õ Ö\n"
        "Misc: º ¬ ¨ ´¸\n"
    )
    sample_latin1 = latin1_text.encode('latin-1', errors='replace')
    with open(fn_latin1, 'wb') as f:
        f.write(_repeat_to_target(sample_latin1, TARGET_SIZE))

    # Fichero con caracteres de control y bytes no imprimibles
    fn_ctrl = "test_control_chars.txt"
    control_bytes = bytearray()
    control_set = list(range(0x00, 0x20)) + [0x7F]
    for b in control_set:
        control_bytes.append(b)
    ansi_sequences = b"\x1b[31mRED\x1b[0m\x1b[32mGREEN\x1b[0m\n"
    random_bytes = bytes(random.randint(0, 255) for _ in range(512))
    sample_ctrl = bytes(control_bytes) + ansi_sequences + random_bytes
    with open(fn_ctrl, 'wb') as f:
        f.write(_repeat_to_target(sample_ctrl, TARGET_SIZE))

    print("Ficheros de prueba (~100 kB) generados:")
    for name in [fn_utf8_lf, fn_utf8_crlf, fn_utf16le, fn_latin1, fn_ctrl]:
        print(f" - {name}")
    return fn_utf8_lf, fn_utf8_crlf, fn_utf16le, fn_latin1, fn_ctrl


def run_all_tests():
    srcs = generate_tests()
    pairs = [
        (srcs[0], "copy_utf8_lf.txt"),
        (srcs[1], "copy_utf8_crlf.txt"),
        (srcs[2], "copy_utf16le.txt"),
        (srcs[3], "copy_latin1.txt"),
        (srcs[4], "copy_control_chars.txt"),
    ]

    results = []
    start_total = time.time()
    for src, dst in pairs:
        print("\n---")
        t0 = time.time()
        ok = roundtrip_mode(src, dst)
        dt = time.time() - t0
        rc = 0 if ok else 1
        results.append((src, dst, rc, dt))
        print(f"Resultado {src} -> {dst}: rc={rc}  tiempo={dt:.2f}s")

    total_time = time.time() - start_total
    ok_count = sum(1 for r in results if r[2] == 0)
    print("\n=== Resumen ===")
    for src, dst, rc, dt in results:
        status = "OK" if rc == 0 else f"FAIL(rc={rc})"
        print(f"{src} -> {dst} : {status}  tiempo={dt:.2f}s")
    print(f"Éxito: {ok_count}/{len(results)}  tiempo total: {total_time:.2f}s")

    # Limpieza de copias
    print("\nLimpieza de ficheros 'copy_*.txt'...")
    deleted = 0
    for _, dst, _, _ in results:
        if os.path.exists(dst):
            try:
                os.remove(dst)
                deleted += 1
            except Exception as e:
                print(f"No se pudo borrar {dst}: {e}")
    print(f"Copias eliminadas: {deleted}/{len(results)}")

    return 0 if ok_count == len(results) else 2


# -------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Genera y prueba ficheros con distintas codificaciones.")
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_send = sub.add_parser('send', help='Leer fichero y guardar stream simulado')
    p_send.add_argument('source')
    p_send.add_argument('simulated_stream')

    p_recv = sub.add_parser('recv', help='Leer stream simulado y escribir fichero de salida')
    p_recv.add_argument('simulated_stream')
    p_recv.add_argument('output')

    p_rt = sub.add_parser('roundtrip', help='Leer desde origen y escribir destino y verificar')
    p_rt.add_argument('source')
    p_rt.add_argument('dest')

    sub.add_parser('generate_tests', help='Genera los ficheros de prueba (~100 kB cada uno)')
    sub.add_parser('run_all', help='Genera ficheros, ejecuta las pruebas y limpia las copias')

    args = parser.parse_args()

    if args.cmd == 'send':
        send_mode(args.source, args.simulated_stream)
    elif args.cmd == 'recv':
        recv_mode(args.simulated_stream, args.output)
    elif args.cmd == 'roundtrip':
        ok = roundtrip_mode(args.source, args.dest)
        if not ok:
            sys.exit(2)
    elif args.cmd == 'generate_tests':
        generate_tests()
    elif args.cmd == 'run_all':
        rc = run_all_tests()
        if rc != 0:
            sys.exit(rc)


if __name__ == "__main__":
    main()
