import os, hashlib, zstandard as zstd

def md5_bytes(data: bytes) -> str:
    """Retorna l'MD5 d'un bloc de bytes."""
    return hashlib.md5(data).hexdigest()

def compress_bytes(b: bytes, level=1) -> bytes:
    """Comprimeix bytes amb zstd al nivell donat."""
    return zstd.ZstdCompressor(level=level).compress(b)

def decompress_bytes(b: bytes) -> bytes:
    """Descomprimeix bytes zstd."""
    return zstd.ZstdDecompressor().decompress(b)

# Fitxers de prova
for fname in ["simulation.txt", "test_utf8_lf.txt", "log.txt"]:
    if not os.path.exists(fname):
        print(f"[AVÍS] No existeix: {fname}")
        continue

    with open(fname, "rb") as f:
        orig = f.read()

    md5_orig = md5_bytes(orig)
    comp = compress_bytes(orig, level=3)
    o, c = len(orig), len(comp)

    ratio = o / c
    reduction = (1 - c / o) * 100

    # Descomprimeix i verifica
    decomp = decompress_bytes(comp)
    md5_decomp = md5_bytes(decomp)
    md5_ok = md5_orig == md5_decomp

    print(f"\nFitxer: {fname}")
    print(f" - Mida original:   {o} bytes")
    print(f" - Mida comprimida: {c} bytes")
    print(f" - Ràtio: {ratio:.2f}:1  |  Reducció: {reduction:.1f}%")
    print(f" - MD5 original:    {md5_orig}")
    print(f" - MD5 descomprès:  {md5_decomp}")
    print(f" - Coincideix?      {'✅ SÍ' if md5_ok else '❌ NO'}")
