"""Probe the JBCF record array of ResourcePath.cfg: 72,764 records x 36 bytes?"""
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
raw = open(os.path.join(r"D:\TLGL\.scratch", "out", "tree", "ResourcePath.cfg"), "rb").read()
N, BLOB_S, BLOB_E = 72764, 3783792, 10853869
BL = BLOB_E - BLOB_S
print(f"blob len={BL}")
for rec in (36, 9, 40, 32):
    span = N * rec
    print(f"  N*{rec} = {span}   blob_start-span = {BLOB_S-span}")

cands = [BLOB_S - 2619524, BLOB_S - 2619524 + 20, BLOB_S - 2619504, 52, 72, 1164268, 1164288]
for st in cands:
    print(f"\n--- candidate array start {st} ({st:#x}) ---")
    chunk = raw[st:st + 36 * 3]
    print("  hex:", chunk.hex())
    for i in range(3):
        r = struct.unpack_from("<9I", raw, st + 36 * i)
        print(f"  rec{i} u32x9 = {r}")
        if all(v <= BL for v in r) and any(r):
            print("     -> values fit blob range")
