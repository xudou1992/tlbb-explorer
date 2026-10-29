"""Numbers for the report. Read-only."""
import collections
import struct
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree\data\tani")
PS = 0x318

def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]

files = [(p.name, p.read_bytes()) for p in TREE.glob("*.tani")]
print("n", len(files))

c10 = collections.Counter()
for name, b in files:
    if len(b) >= 0x110:
        c10[u32(b, 0x10C)] += 1
    else:
        c10["short"] += 1
print("u32@10c", c10)

# ani at 0x40
print("\nani@0x40:")
for name, b in files:
    if len(b) >= 0x44 and b[0x40:0x43] == b"ani":
        z = b.find(b"\x00", 8)
        print(" ", name, "path", b[8:z], "around", b[0x38:0x48])

# record0 name
r0 = collections.Counter()
r_later_empty = collections.Counter()
binary_ex = []
for name, b in files:
    if len(b) < 0x140 or u32(b, 0x130) != 0:
        continue
    n = u32(b, 0x138)
    if u32(b, 0x13C) != n or n < 1:
        continue
    rec = b[0x140:0x140 + PS]
    if rec[0] == 0:
        r0["empty"] += 1
    elif 32 <= rec[0] < 127:
        r0["cstr"] += 1
    else:
        r0["bin"] += 1
        if len(binary_ex) < 3:
            binary_ex.append((name, rec[:16].hex()))
print("record0", r0, "examples bin", binary_ex)

# group boundary bytes: first particle+sound file with groups>=2
print("\ngroup boundary:")
shown = 0
for name, b in files:
    if len(b) < 0x140 or u32(b, 0x10C) != 2 or u32(b, 0x130) != 0:
        continue
    n = u32(b, 0x138)
    if u32(b, 0x13C) != n:
        continue
    tail = b[0x140 + n * PS:]
    if len(tail) < 16:
        continue
    a, c, g, d = struct.unpack_from("<4I", tail, 0)
    if a != 1 or c != 4 or g < 2:
        continue
    boundary = 5 * 0x4B0
    print(name, "groups", g, "d", d)
    chunk = tail[boundary - 16:boundary + 32]
    print(chunk.hex())
    # also record1 start vs the 16
    print("sep", tail[boundary:boundary + 16].hex())
    print("next", tail[boundary + 16:boundary + 32].hex())
    shown += 1
    if shown >= 3:
        break

# size table
sz = collections.Counter(len(b) for _, b in files)
print("\nsize table")
for s, c in sz.most_common():
    print(f"  {s:6d} {c:4d}")

# zero region 0x110-0x12c
zok = sum(1 for _, b in files if len(b) >= 0x130 and b[0x110:0x130] == b"\x00" * 0x20)
print("0x110:0x130 zero", zok, "/", sum(1 for _, b in files if len(b) >= 0x130))

# path end max
ends = [b.find(b"\x00", 8) for _, b in files]
print("nul offset min/max", min(ends), max(ends))

# sum bytes
print("sum", sum(len(b) for _, b in files))
