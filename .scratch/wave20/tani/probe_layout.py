"""Cluster .tani by size and find stable offsets. Read-only."""
import collections
import struct
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree\data\tani")
OUT = Path(__file__).resolve().parent

files = []
for p in TREE.glob("*.tani"):
    b = p.read_bytes()
    z = b.find(b"\x00", 8)
    files.append((p.name, b, z))

print("files", len(files))

# strings
def strings(b, minlen=4):
    out = []
    i = 0
    n = len(b)
    while i < n:
        if 32 <= b[i] < 127:
            j = i
            while j < n and 32 <= b[j] < 127:
                j += 1
            if j - i >= minlen and (j == n or b[j] == 0):
                out.append((i, b[i:j].decode("latin1")))
            i = j + 1
        else:
            i += 1
    return out

extc = collections.Counter()
kw = collections.Counter()
start_off = collections.Counter()
KEYWORDS = (b".pu", b".mesh", b".ani", b".wav", b".ogg", b".tga", b"FPS:", b"D3D",
            b"bip01", b"Bip01", b"Copyright", b"Untitled", b"RenderItem", b"MIN2",
            b"JBCF", b"JBPU", b"GATA")
kw_files = collections.Counter()
for name, b, z in files:
    hit = set()
    for k in KEYWORDS:
        if k in b:
            kw[k.decode("latin1")] += b.count(k)
            hit.add(k.decode("latin1"))
    for h in hit:
        kw_files[h] += 1
    for off, s in strings(b, 6):
        if s.endswith(".pu") or s.endswith(".mesh") or s.endswith(".ani") or s.endswith(".tani"):
            extc[s.rsplit(".", 1)[-1] + f"@{off}"] += 1
            start_off[(s.rsplit(".", 1)[-1], off)] += 1

print("keyword file hits", kw_files.most_common())
print("keyword occ", kw.most_common())
print("ext@offset top")
for (ext, off), c in start_off.most_common(25):
    print(f"  .{ext} @ {off:#x}  {c}")

# body length after nul
bl = collections.Counter(len(b) - (z + 1) for _, b, z in files)
print("distinct body lens", len(bl), "top", bl.most_common(15))

# within each size class, constant byte mask
def const_report(group, label, head=0x180):
    n = len(group)
    L = len(group[0][1])
    const = bytearray(L)
    vary = bytearray(L)
    # first as base
    base = group[0][1]
    same = [True] * L
    for _, b, _ in group[1:]:
        for i, (x, y) in enumerate(zip(base, b)):
            if x != y:
                same[i] = False
    # also require all equal to base[i]
    ccount = sum(same)
    # runs of constant
    runs = []
    i = 0
    while i < L:
        if same[i]:
            j = i
            while j < L and same[j]:
                j += 1
            if j - i >= 4:
                runs.append((i, j, base[i:j]))
            i = j
        else:
            i += 1
    print(f"\n== size {L} n={n} const_bytes={ccount}/{L} ({100*ccount/L:.1f}%) runs>4B: {len(runs)}")
    # print constant runs that are not all-zero, first 12
    shown = 0
    for a, c, raw in runs:
        if raw == b"\x00" * len(raw):
            continue
        if shown >= 8:
            break
        txt = "".join(chr(x) if 32 <= x < 127 else "." for x in raw[:24])
        print(f"  const {a:#06x}-{c:#06x} ({c-a}B) {raw[:16].hex()} {txt}")
        shown += 1
    # zero-const runs summarized
    zruns = [(a, c) for a, c, raw in runs if raw == b"\x00" * len(raw) and c - a >= 8]
    print("  zero-const runs >=8", [(hex(a), c - a) for a, c in zruns[:12]], "count", len(zruns))
    return same, base

by = collections.defaultdict(list)
for rec in files:
    by[len(rec[1])].append(rec)

# dominant classes
for sz, _n in collections.Counter(len(b) for _, b, _ in files).most_common(8):
    const_report(by[sz], sz)

# cross-check: among files >= 0x160, is there a .pu/.mesh cstring at a shared offset?
print("\n== name slot scan (files with len>=0x160) ==")
big = [rec for rec in files if len(rec[1]) >= 0x160]
slot = collections.Counter()
for name, b, z in big:
    # find first .pu or .mesh or .ogg after offset 0x80
    for ext in (b".pu\x00", b".mesh\x00", b".ogg\x00", b".wav\x00", b".ani\x00"):
        i = b.find(ext, 0x40)
        if i > 0:
            # walk back to start of string
            s = i
            while s > 0 and 32 <= b[s - 1] < 127:
                s -= 1
            slot[(ext, s)] += 1
            break
    else:
        slot[("none", -1)] += 1
print(" first embedded name start", slot.most_common(15), "of", len(big))

# u32 constants at fixed offsets for ALL files that are long enough, offset 0..0x40 step 4
print("\n== u32 stability at fixed offs (all files long enough) ==")
for off in range(0, 0x80, 4):
    vals = collections.Counter()
    n = 0
    for _, b, z in files:
        if off + 4 <= len(b) and off + 4 <= z:  # still inside the path string region? skip if overlaps string
            pass
        if off + 4 <= len(b):
            # only count if this offset is PAST the path NUL
            if off > z:
                vals[struct.unpack_from("<I", b, off)[0]] += 1
                n += 1
    if n < 100:
        continue
    top, c = vals.most_common(1)[0]
    if c >= 0.8 * n and (top < 64 or top in (0x3f800000, 0xffffffff)):
        print(f"  off {off:#x} n={n} top={top} ({c/n:.0%}) distinct={len(vals)}")

# How many files have the self path equal to data/tani/<name>
kinds = collections.Counter()
mismatch_names = []
for name, b, z in files:
    s = b[8:z].decode("latin1")
    expect = "data/tani/" + name
    if s == expect:
        kinds["self"] += 1
    elif s == name:
        kinds["bare"] += 1
    else:
        kinds["other"] += 1
        if len(mismatch_names) < 8:
            mismatch_names.append((name, s))
print("self-path kinds", kinds)
print("other examples", mismatch_names)

# pointer-like u64 at 8-aligned offsets AFTER a per-file aligned body start
# Try: payload begins at align8(z+1) ONLY if pad is zero; else at z+1
print("\n== where do 0x000001xx / 0x00007FFx pointers sit relative to NUL ==")
rel = collections.Counter()
nptr = 0
for name, b, z in files:
    # scan u64 aligned to 8 from offset 0
    for off in range(0, len(b) - 7, 8):
        v = struct.unpack_from("<Q", b, off)[0]
        hi = v >> 48  # top 16 of the 64
        # user canonical: top 16 bits 0 and next bits look like 0x00007FF or 0x000001xx
        if v >> 40 in range(0x7FF0, 0x8000) or (0x100 <= (v >> 40) <= 0x200):
            rel[off - (z + 1)] += 1
            nptr += 1
print("ptr-like u64", nptr)
print("offset relative to NUL+1 top", rel.most_common(12))
