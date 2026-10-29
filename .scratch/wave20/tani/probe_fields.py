"""Field map of the 0x318 particle record and sound-tail grammar. Read-only."""
import collections
import struct
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree\data\tani")
HDR = 0x140
PS = 0x318
SS = 0x4B0  # 1200

files = []
for p in sorted(TREE.glob("*.tani")):
    b = p.read_bytes()
    z = b.find(b"\x00", 8)
    files.append((p.name, b, z))


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def cstr(b, o, limit):
    if o >= len(b) or not (32 <= b[o] < 127):
        return None
    j = o
    end = min(len(b), o + limit)
    while j < end and 32 <= b[j] < 127:
        j += 1
    if j < len(b) and b[j] == 0 and j > o:
        return b[o:j].decode("latin1")
    return None


# ---- particle records from files where c10c==1 and size matches exactly
recs = []  # (name, idx, recbytes)
pure = []
for name, b, z in files:
    if len(b) < HDR or z > 0xF0:
        continue
    if u32(b, 0x10C) != 1:
        continue
    n = u32(b, 0x138)
    if n == 0 or n > 40:
        continue
    if len(b) != HDR + n * PS:
        continue
    if u32(b, 0x13C) != n:
        continue
    pure.append((name, b, n))
    for i in range(n):
        recs.append(b[HDR + i * PS:HDR + (i + 1) * PS])

print("pure files", len(pure), "records", len(recs))

# per-offset class across records
N = len(recs)
print("\n== particle record offset classes (stride 0x318) ==")
# group into runs
classes = []
for off in range(PS):
    vals = [r[off] for r in recs]
    c = collections.Counter(vals)
    top, tc = c.most_common(1)[0]
    if tc == N and top == 0:
        classes.append("Z")
    elif tc == N:
        classes.append("C")  # constant nonzero
    elif tc >= 0.95 * N and top == 0:
        classes.append("z")  # almost always 0
    else:
        # ascii?
        if all(32 <= v < 127 or v == 0 for v in vals) and sum(32 <= v < 127 for v in vals) > 0.2 * N:
            classes.append("S")
        else:
            classes.append("V")

# compress runs
i = 0
while i < PS:
    j = i
    while j < PS and classes[j] == classes[i]:
        j += 1
    lab = classes[i]
    if j - i >= 2 or lab in "CS":
        extra = ""
        if lab == "C":
            raw = bytes(recs[0][i:j])
            extra = " " + raw[:12].hex()
        print(f"  {i:#06x}-{j:#06x} ({j-i:4d}) {lab}{extra}")
    i = j

# string slots: try offsets where many records have a cstring
print("\n== cstring hit rates inside particle record ==")
for off in range(0, PS, 1):
    hits = 0
    ex = None
    for r in recs:
        s = cstr(r, off, 96)
        if s and len(s) >= 3:
            hits += 1
            ex = s
    if hits >= 0.5 * N and (off < 4 or classes[off - 1] != "S"):
        # only report starts (prev not S)
        if off == 0 or classes[off - 1] != "S":
            print(f"  +{off:#06x}  {hits}/{N}  eg {ex[:60] if ex else ''}")

# u32 small-int fields: low distinct and not pointer
print("\n== u32 fields with distinct<=12 and not mostly zero ==")
for off in range(0, PS - 3, 4):
    vals = collections.Counter(struct.unpack_from("<I", r, off)[0] for r in recs)
    if len(vals) <= 12 and vals.most_common(1)[0][0] != 0:
        top = vals.most_common(6)
        print(f"  +{off:#06x} distinct={len(vals)} {top}")

# floats that are 1.0 often
print("\n== f32 often ~1 or nice ==")
for off in range(0, PS - 3, 4):
    ones = 0
    nice = 0
    for r in recs:
        f = struct.unpack_from("<f", r, off)[0]
        if f == 1.0:
            ones += 1
        elif f == f and abs(f) < 10000:
            nice += 1
    if ones >= 0.8 * N:
        print(f"  +{off:#06x} f32==1 {ones}/{N}")

# ---- sound tail grammar for c10c==2
print("\n== sound tail walk ==")


def expect_len(groups, slots, sep, foot):
    return groups * slots * SS + max(groups - 1, 0) * sep + foot


ok = fail = 0
fail_ex = collections.Counter()
# also try to discover slots/sep/foot from the u32 header
# Observed: groups = u32@+8, slots=5, sep=16, foot=28
for name, b, z in files:
    if len(b) < HDR or z > 0xF0:
        continue
    if u32(b, 0x10C) != 2:
        continue
    n = u32(b, 0x138)
    if not (1 <= n <= 40):
        fail += 1
        fail_ex["bad n"] += 1
        continue
    pend = HDR + n * PS
    if pend > len(b):
        fail += 1
        fail_ex["pend>len"] += 1
        continue
    tail = b[pend:]
    if len(tail) < 16:
        fail += 1
        fail_ex["tiny tail"] += 1
        continue
    a, c, groups, d = struct.unpack_from("<4I", tail, 0)
    el = expect_len(groups, 5, 16, 28)
    if a == 1 and c == 4 and 1 <= groups <= 32 and len(tail) == el:
        ok += 1
    else:
        fail += 1
        fail_ex[(a if a < 10 else "a?", c if c < 20 else "c?", groups if groups < 40 else "g?", len(tail), el if groups < 40 else -1)] += 1

print(f"  c10c==2 matched 5*1200 groups: {ok} fail {fail}")
print("  fail top", fail_ex.most_common(12))

# c10c==1 but not pure
print("\n== c10c==1 not pure ==")
odd = collections.Counter()
for name, b, z in files:
    if len(b) < HDR or z > 0xF0:
        continue
    if u32(b, 0x10C) != 1:
        continue
    n = u32(b, 0x138)
    if len(b) == HDR + n * PS and u32(b, 0x13C) == n:
        continue
    # what is at 0x140
    s = cstr(b, 0x140, 80) or ""
    ext = s.rsplit(".", 1)[-1] if "." in s else ("empty" if not s else "nodot")
    odd[(ext, len(b), n, u32(b, 0x13C))] += 1
print(" odd", len(odd))
for k, c in odd.most_common(20):
    print(f"  {c:4d} {k}")

# 304-byte files: first nonzero after path, and whether identical skeleton
print("\n== 304 files ==")
small = [(name, b, z) for name, b, z in files if len(b) == 304]
print(" n", len(small))
for name, b, z in small:
    print(f"  {name} nul={z:#x} path={b[8:z].decode('latin1')}")
