"""Details for the 10 non-walkers, footers, name buffers, db deltas. Read-only."""
import collections
import sqlite3
import struct
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree\data\tani")
DB = r"D:\TLGL\.scratch\resources.db"
PS = 0x318
SS = 0x4B0

def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]

def hx(b, n=64):
    lines = []
    for i in range(0, min(len(b), n), 16):
        c = b[i:i+16]
        h = " ".join(f"{x:02x}" for x in c)
        t = "".join(chr(x) if 32 <= x < 127 else "." for x in c)
        lines.append(f"  {i:04x} {h:<48} {t}")
    return "\n".join(lines)

# the odd file
p = TREE / "boss_tani_liqiushui_shifa07.tani"
b = p.read_bytes()
z = b.find(b"\x00", 8)
print("LIQIU", len(b), "path", b[8:z])
print("u32 0x100..0x140:")
for o in range(0x100, 0x140, 4):
    print(f"  {o:#x} {u32(b,o)}")
# strings
i = 0
print("strings:")
while i < len(b):
    if 32 <= b[i] < 127:
        j = i
        while j < len(b) and 32 <= b[j] < 127:
            j += 1
        if j - i >= 6 and j < len(b) and b[j] == 0:
            print(f"  {i:#x} {b[i:j].decode('latin1')[:80]}")
        i = j + 1
    else:
        i += 1

print("\n== 304 const bytes ==")
small = []
for name in [
    "boss_tani_huoshaochibi_shifa01.tani",
    "boss_tani_jiaolongluanwu_shifa01.tani",
    "boss_tani_shaxing_gss_fsf_hit01.tani",
    "boss_zhuobufan_shifa.tani",
    "pets_tani_xuruo01.tani",
    "pt_tani_chujizhiliao01.tani",
    "pt_tani_chujizhiliao02.tani",
    "pt_tani_ranshaoxianjing01.tani",
    "pt_tani_ranshaoxianjing02.tani",
]:
    small.append((TREE / name).read_bytes())
base = small[0]
same = [all(s[i] == base[i] for s in small) for i in range(304)]
print("const bytes", sum(same), "/304")
# runs
i = 0
while i < 304:
    if same[i]:
        j = i
        while j < 304 and same[j]:
            j += 1
        if j - i >= 4:
            raw = base[i:j]
            tag = "zero" if raw == b"\x00"*len(raw) else raw[:8].hex()
            print(f"  {i:#x}-{j:#x} ({j-i}) {tag}")
        i = j
    else:
        i += 1

# Does 0x58 hold u32 8 in the 304s? and pointer pairs
print("\n304 u32@0x54,58,80,88,10c")
for s in small:
    z = s.find(b"\x00", 8)
    print(" ", z, [u32(s, o) for o in (0x50, 0x54, 0x58, 0x80, 0x88, 0x108, 0x10c)])

# footer / sep census on walked sound blocks
print("\n== footer and sep ==")
foot_c = collections.Counter()
sep_c = collections.Counter()
d_c = collections.Counter()
rec0_u = collections.defaultdict(collections.Counter)
n_sound_rec = 0
for pth in TREE.glob("*.tani"):
    b = pth.read_bytes()
    if len(b) < 0x140:
        continue
    if u32(b, 0x130) == 0 and u32(b, 0x10C) == 2 and u32(b, 0x138) == u32(b, 0x13C):
        n = u32(b, 0x138)
        pend = 0x140 + n * PS
        tail = b[pend:]
    elif u32(b, 0x130) == 1 and u32(b, 0x134) == 4:
        tail = b[0x130:]
    else:
        continue
    if len(tail) < 16:
        continue
    a, c, groups, d = struct.unpack_from("<4I", tail, 0)
    if a != 1 or c != 4:
        continue
    need = groups * 5 * SS + (groups - 1) * 16 + 28
    if len(tail) != need:
        continue
    d_c[d] += 1
    foot_c[tail[-28:]] += 1
    off = 0
    for g in range(groups):
        if g:
            sep_c[tail[off:off+16]] += 1
            off += 16
        rec = tail[off:off+SS]
        if g == 0:
            for o in range(0, 16, 4):
                rec0_u[o][u32(rec, o)] += 1
        n_sound_rec += 1
        off += SS

print("sound records", n_sound_rec, "distinct footers", len(foot_c), "distinct seps", len(sep_c))
print("u32 d (4th header word) top", d_c.most_common(8))
print("first-record u32s:")
for o, c in rec0_u.items():
    print(f"  +{o:#x} {c.most_common(4)}")
# show one footer and one sep
foot, fc = foot_c.most_common(1)[0]
print("most common footer x", fc, foot.hex())
if sep_c:
    sep, sc = sep_c.most_common(1)[0]
    print("most common sep x", sc, "/", sum(sep_c.values()), sep.hex())

# particle name buffer: max strlen at +0 and zero-fill until ?
print("\n== particle name buffer ==")
maxlen = collections.Counter()
# for pure files, for each record, cstring at 0
ends = collections.Counter()
for pth in list(TREE.glob("*.tani"))[:]:
    b = pth.read_bytes()
    if len(b) < 0x140 or u32(b, 0x130) != 0:
        continue
    n = u32(b, 0x138)
    if u32(b, 0x13C) != n or not (1 <= n <= 64):
        continue
    if u32(b, 0x10C) == 1 and len(b) != 0x140 + n * PS:
        continue
    if u32(b, 0x10C) not in (1, 2):
        continue
    for i in range(n):
        rec = b[0x140 + i * PS:0x140 + (i + 1) * PS]
        if rec[0] == 0:
            ends["empty"] += 1
            continue
        if not (32 <= rec[0] < 127):
            ends["binary"] += 1
            continue
        z = rec.find(b"\x00")
        ends["cstr"] += 1
        maxlen[z] += 1
print("name kinds", ends)
print("strlen max", max((k for k in maxlen if isinstance(k, int)), default=None), "top", maxlen.most_common(5))

# db mismatch summary
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
mm = []
for path, original in con.execute("select path, original from resources where ext='.tani'"):
    disk = (TREE / Path(path).name).read_bytes()
    if len(disk) != original:
        mm.append((path, len(disk), original, len(disk) - original))
print("\ndb mismatches", len(mm))
print("delta top", collections.Counter(d for *_, d in mm).most_common())
# do mismatched files still walk? we'll just list sizes
print("disk sizes of mismatched", collections.Counter(d for _, d, _, _ in mm).most_common(8))

# size histogram buckets already known; distinct sizes
sizes = collections.Counter()
for pth in TREE.glob("*.tani"):
    sizes[pth.stat().st_size] += 1
print("distinct sizes", len(sizes), "min", min(sizes), "max", max(sizes), "sum", sum(s*c for s,c in sizes.items()))

# self path
kinds = collections.Counter()
for pth in TREE.glob("*.tani"):
    b = pth.read_bytes()
    z = b.find(b"\x00", 8)
    s = b[8:z].decode("latin1")
    exp = "data/tani/" + pth.name
    if s == exp:
        kinds["equals data/tani/name"] += 1
    elif s == pth.name:
        kinds["bare filename"] += 1
    elif s.endswith(".tani"):
        kinds["other .tani path"] += 1
    else:
        kinds["other"] += 1
print("self path", kinds)

# ani markers full file not just head
ani = collections.Counter()
for pth in TREE.glob("*.tani"):
    b = pth.read_bytes()
    ani["copyright"] += b[:10] == b"Copyright "
    ani["MIN2"] += b.find(b"MIN2") >= 0
    ani["JBCF"] += b.find(b"JBCF") >= 0
    ani["JBPU"] += b.find(b"JBPU") >= 0
print("embedded markers", ani)
