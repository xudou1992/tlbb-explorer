"""Record-size hypothesis: 0x140 + n * 0x318. Read-only."""
import collections
import struct
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree\data\tani")
OUT = Path(__file__).resolve().parent
HDR = 0x140
STRIDE = 0x318

files = []
for p in sorted(TREE.glob("*.tani")):
    b = p.read_bytes()
    z = b.find(b"\x00", 8)
    files.append((p.name, b, z))


def cstrings(b, minlen=3):
    out = []
    i = 0
    while i < len(b):
        if 32 <= b[i] < 127:
            j = i
            while j < len(b) and 32 <= b[j] < 127:
                j += 1
            if j - i >= minlen and j < len(b) and b[j] == 0:
                out.append((i, b[i:j].decode("latin1")))
            i = max(j, i + 1)
        else:
            i += 1
    return out


def pick(sz):
    return next(rec for rec in files if len(rec[1]) == sz)


lines = []
for sz in (304, 1112, 1904, 2696, 7140, 6332, 7932):
    name, b, z = pick(sz)
    lines.append(f"\n===== {sz} {name} nul={z:#x} str={b[8:z]!r}")
    # header u32 from 0x40 to 0x140 if past nul
    words = []
    for off in range(0x40, min(HDR, len(b) - 3), 4):
        v = struct.unpack_from("<I", b, off)[0]
        if v:
            words.append(f"{off:#x}:{v if v < 100000 else hex(v)}")
    lines.append("  nonzero u32 @40..140: " + ", ".join(words[:40]))
    ss = cstrings(b, 4)
    lines.append("  strings:")
    for off, s in ss:
        if off < 8:
            continue
        lines.append(f"    {off:#06x} {s[:80]}")

# fit
fit = 0
rem_hist = collections.Counter()
by_n = collections.Counter()
bad = []
for name, b, z in files:
    L = len(b)
    if L < HDR:
        rem_hist[("short", L)] += 1
        bad.append((name, L, "short"))
        continue
    rem = L - HDR
    if rem % STRIDE == 0:
        fit += 1
        by_n[rem // STRIDE] += 1
    else:
        q, r = divmod(rem, STRIDE)
        rem_hist[(q, r)] += 1
        if len(bad) < 30:
            bad.append((name, L, q, r))

lines.append(f"\n== fit 0x140+n*0x318: {fit}/{len(files)}")
lines.append(f"n histogram {sorted(by_n.items())}")
lines.append(f"nonfit patterns top {rem_hist.most_common(20)}")
lines.append("bad examples " + str(bad[:12]))

# u32@0x10c and @0x138 vs n for fitting files
corr = collections.Counter()
for name, b, z in files:
    L = len(b)
    if L < HDR or (L - HDR) % STRIDE:
        continue
    n = (L - HDR) // STRIDE
    c10c = struct.unpack_from("<I", b, 0x10C)[0]
    c138 = struct.unpack_from("<I", b, 0x138)[0]
    c13c = struct.unpack_from("<I", b, 0x13C)[0]
    corr[(n, c10c, c138, c13c)] += 1
lines.append("fit files (n, u32@10c, @138, @13c) top:")
for k, c in corr.most_common(20):
    lines.append(f"  {k} x{c}")

# For non-fitting, same header words vs remainder
lines.append("\nnonfit header signature (u32@10c,138,13c, len, rem%0x318):")
sig = collections.Counter()
for name, b, z in files:
    L = len(b)
    if L < HDR or (L - HDR) % STRIDE == 0:
        continue
    c10c = struct.unpack_from("<I", b, 0x10C)[0]
    c138 = struct.unpack_from("<I", b, 0x138)[0]
    c13c = struct.unpack_from("<I", b, 0x13C)[0]
    q, r = divmod(L - HDR, STRIDE)
    sig[(c10c, c138, c13c, q, r, L)] += 1
for k, c in sig.most_common(25):
    lines.append(f"  {k} x{c}")

text = "\n".join(lines)
(OUT / "rec_dump.txt").write_text(text, encoding="utf-8")
print(text[:6000])
print("\n--- wrote rec_dump.txt", len(text))
