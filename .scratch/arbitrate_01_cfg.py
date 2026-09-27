"""Arbitration step 1: byte-level survey of out/tree/ResourcePath.cfg (is it JBCF? how are paths packed?)."""
import re
import struct
from pathlib import Path

CFG = Path(r"D:\TLGL\.scratch\out\tree\ResourcePath.cfg")
raw = CFG.read_bytes()
out = []
W = out.append
W(f"size={len(raw)} magic={raw[:4]!r} version={struct.unpack_from('<I', raw, 8)[0]}")
W("header u32[0:24]: " + str(struct.unpack_from('<24I', raw, 0)))

# printable runs
runs = [(m.start(), m.end()) for m in re.finditer(rb'[\x20-\x7e]{16,}', raw)]
tot = sum(e - s for s, e in runs)
W(f"printable runs>=16B: {len(runs)}  total bytes {tot} ({100*tot/len(raw):.1f}% of file)")
runs_sorted = sorted(runs, key=lambda r: -(r[1] - r[0]))[:10]
for s, e in runs_sorted:
    W(f"   run @{s} len={e-s} head={raw[s:s+70]!r}")

# one giant run?
big = [r for r in runs if r[1] - r[0] > 100000]
W(f"runs > 100KB: {len(big)} {big[:5]}")
if big:
    s, e = big[0]
    W(f"biggest run starts with {raw[s:s+90]!r}")
    W(f"biggest run ends   with {raw[e-90:e]!r}")

# NUL structure right after header
W("bytes 12..40 hex: " + raw[12:40].hex())
# count of 0x00 overall
W(f"NUL count in file: {raw.count(0)}")
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
print("\n".join(out))
