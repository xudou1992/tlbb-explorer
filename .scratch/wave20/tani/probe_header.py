"""Header-boundary hypotheses over every .tani. Read-only."""
import collections
import sqlite3
import struct
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree")
DB = r"D:\TLGL\.scratch\resources.db"
OUT = Path(__file__).resolve().parent

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = list(con.execute(
    "select path, name, original from resources where ext='.tani'"
))

files = []
for path, name, original in rows:
    p = TREE / path.replace("/", "\\")
    b = p.read_bytes()
    z = b.find(b"\x00", 8)
    s = b[8:z].decode("latin1")
    files.append((path, name, original, b, z, s))

# a4 pad
bad4 = 0
for path, name, original, b, z, s in files:
    nxt = z + 1
    a4 = (nxt + 3) & ~3
    if b[nxt:a4] != b"\x00" * (a4 - nxt):
        bad4 += 1
print("a4 pad nonzero", bad4, "/", len(files))

# immediate byte after NUL
after = collections.Counter()
for path, name, original, b, z, s in files:
    if z + 1 < len(b):
        after[b[z + 1]] += 1
print("byte after NUL top", after.most_common(8), "distinct", len(after))

# fixed windows from offset 8: how far is the zero run after first NUL,
# and does a hard boundary (32/48/64/...) contain only the string + zeros
print("\n=== zero-run after NUL ===")
run = collections.Counter()
for path, name, original, b, z, s in files:
    i = z + 1
    while i < len(b) and b[i] == 0:
        i += 1
    run[i - (z + 1)] += 1
print("zero bytes after NUL (top)", run.most_common(20))
print("zero-run == 0 (data immediate)", run[0])

# candidate fixed field end offsets (absolute)
print("\n=== fixed end offset: zeros from NUL+1 through end-1, and end<len ===")
for end in range(16, 257, 4):
    ok = 0
    overrun = 0  # string NUL at or after end
    nonzero_pad = 0
    for path, name, original, b, z, s in files:
        if z >= end:
            overrun += 1
            continue
        if end > len(b):
            continue
        if b[z + 1:end] == b"\x00" * (end - (z + 1)):
            ok += 1
        else:
            nonzero_pad += 1
    if ok > 2000 or overrun == 0 and ok > 100:
        print(f"  end={end:3d}  clean_pad={ok:4d}  str_overruns={overrun:4d}  dirty={nonzero_pad:4d}")

# string length distribution
lc = collections.Counter(z - 8 for *_, z, s in files)
print("\nstring len min/max", min(lc), max(lc), "distinct", len(lc))
print("len top", lc.most_common(8))

# size mismatch detail
mm = [(path, len(b), original) for path, name, original, b, z, s in files if len(b) != original]
print("\nsize mismatch", len(mm))
delta = collections.Counter((d - o) for _, d, o in mm)
print("disk-db delta top", delta.most_common(10))
print("examples", mm[:8])

# hex of 3 smallest unique sizes
by_size = {}
for rec in files:
    by_size.setdefault(len(rec[3]), []).append(rec)

def hx(b, n=304):
    lines = []
    b = b[:n]
    for i in range(0, len(b), 16):
        chunk = b[i:i + 16]
        h = " ".join(f"{x:02x}" for x in chunk)
        t = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
        lines.append(f"{i:04x}  {h:<48}  {t}")
    return "\n".join(lines)

out = []
shown = 0
for sz in sorted(by_size):
    if shown >= 4:
        break
    path, name, original, b, z, s = by_size[sz][0]
    out.append(f"\n===== size {sz} nfiles={len(by_size[sz])} {path} nul={z} str={s!r} db={original}")
    out.append(hx(b, min(sz, 512)))
    shown += 1
# also one where a4 pad would be dirty if any, and one bare-name, one other-path
bare = next(rec for rec in files if "/" not in rec[5])
other = next(rec for rec in files if rec[5] != rec[0] and "/" in rec[5])
out.append(f"\n===== BARE {bare[0]} str={bare[5]!r} n={len(bare[3])} nul={bare[4]}")
out.append(hx(bare[3], 256))
out.append(f"\n===== OTHER {other[0]} str={other[5]!r} n={len(other[3])} nul={other[4]}")
out.append(hx(other[3], 256))

# two files of same size diff
same = next(v for v in by_size.values() if len(v) >= 2 and len(v[0][3]) <= 400)
a, c = same[0], same[1]
out.append(f"\n===== DIFF {a[0]} vs {c[0]} size {len(a[3])}")
ba, bc = a[3], c[3]
diffs = [i for i in range(len(ba)) if ba[i] != bc[i]]
out.append(f"diff bytes {len(diffs)}")
# group ranges
if diffs:
    ranges = []
    s0 = diffs[0]
    prev = diffs[0]
    for i in diffs[1:]:
        if i == prev + 1:
            prev = i
        else:
            ranges.append((s0, prev))
            s0 = prev = i
    ranges.append((s0, prev))
    out.append("ranges " + ", ".join(f"{a_}-{b_}" for a_, b_ in ranges[:40]))

(OUT / "header_dump.txt").write_text("\n".join(out), encoding="utf-8")
print("wrote header_dump.txt lines", len(out))
print("size classes", len(by_size))
print("most common sizes", collections.Counter(len(rec[3]) for rec in files).most_common(12))
