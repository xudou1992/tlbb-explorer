"""Try one grammar on every .tani. Read-only. Prints pass/fail."""
import collections
import struct
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree\data\tani")
PS = 0x318
SS = 0x4B0  # 1200
SLOTS = 5
SEP = 16
FOOT = 28

def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]

def sound_block_len(groups):
    if groups < 1:
        return None
    return groups * SLOTS * SS + (groups - 1) * SEP + FOOT

def check_sound(buf):
    """Return None if the buffer is exactly one sound block, else a reason."""
    if len(buf) < 16:
        return "short"
    a, b, groups, d = struct.unpack_from("<4I", buf, 0)
    if a != 1 or b != 4:
        return f"hdr {a},{b},{groups},{d}"
    if not (1 <= groups <= 64):
        return f"groups {groups}"
    need = sound_block_len(groups)
    if len(buf) != need:
        return f"len {len(buf)} != {need} groups={groups} d={d}"
    # walk groups: each is 5 * 1200, separator 16 between, footer 28 after last
    off = 0
    for g in range(groups):
        if g:
            # separator must be consumed; don't require its bytes yet
            off += SEP
        for s in range(SLOTS):
            rec = buf[off:off + SS]
            if len(rec) != SS:
                return "trunc rec"
            # path cstring at +0x10 must be printable or empty
            if rec[0x10] != 0 and not (32 <= rec[0x10] < 127):
                return f"path byte g={g} s={s} {rec[0x10]:#x}"
            # NUL somewhere in the name buffer before a reasonable limit
            if rec[0x10] != 0:
                z = rec.find(b"\x00", 0x10, 0x110)
                if z < 0:
                    return "path no nul"
            off += SS
    if off + FOOT != len(buf):
        return f"cursor {off}+{FOOT} != {len(buf)}"
    return None

files = []
for p in sorted(TREE.glob("*.tani")):
    b = p.read_bytes()
    z = b.find(b"\x00", 8)
    files.append((p.name, b, z))

reasons = collections.Counter()
ok_kind = collections.Counter()
fails = []

for name, b, z in files:
    if b[:4] != b"GATA":
        reasons["magic"] += 1
        fails.append((name, "magic"))
        continue
    if len(b) < 8 or u32(b, 4) != 0:
        reasons["u32@4"] += 1
        fails.append((name, "u32@4"))
        continue
    if z < 9 or z > 400:
        reasons["path"] += 1
        fails.append((name, "path"))
        continue
    path = b[8:z]
    if not all(32 <= c < 127 for c in path) or not path.endswith(b".tani"):
        reasons["path-bytes"] += 1
        fails.append((name, "path-bytes"))
        continue

    if len(b) == 0x130:
        # no count field exists; do not pretend
        reasons["fixed-304"] += 1
        fails.append((name, "fixed-304"))
        continue

    if len(b) < 0x140:
        reasons["between"] += 1
        fails.append((name, f"len {len(b)}"))
        continue

    w130 = u32(b, 0x130)
    w134 = u32(b, 0x134)
    if w130 == 0:
        n = u32(b, 0x138)
        c13 = u32(b, 0x13C)
        c10 = u32(b, 0x10C)
        if not (1 <= n <= 64) or c13 != n:
            reasons["particle-count"] += 1
            fails.append((name, f"count n={n} c13={c13} c10={c10} len={len(b)}"))
            continue
        pend = 0x140 + n * PS
        if pend > len(b):
            reasons["particle-over"] += 1
            fails.append((name, "over"))
            continue
        if c10 == 1:
            if pend == len(b):
                ok_kind["particle"] += 1
            else:
                reasons["particle-tail"] += 1
                fails.append((name, f"particle leftover {len(b)-pend}"))
        elif c10 == 2:
            err = check_sound(b[pend:])
            if err is None:
                ok_kind["particle+sound"] += 1
            else:
                reasons["sound-after " + err] += 1
                fails.append((name, "sound-after " + err))
        else:
            reasons[f"c10c={c10}"] += 1
            fails.append((name, f"c10c {c10}"))
    elif w130 == 1 and w134 == 4:
        err = check_sound(b[0x130:])
        if err is None:
            ok_kind["sound-only"] += 1
        else:
            reasons["sound-only " + err] += 1
            fails.append((name, "sound-only " + err))
    else:
        reasons[f"branch {w130},{w134}"] += 1
        fails.append((name, f"branch {w130},{w134} len={len(b)}"))

print("files", len(files))
print("ok", dict(ok_kind), "sum", sum(ok_kind.values()))
print("fail", sum(reasons.values()))
print("reasons:")
for k, c in reasons.most_common(30):
    print(f"  {c:4d} {k}")
print("fail examples:")
for row in fails[:25]:
    print(" ", row)
