"""Arbitration: recount .scene instances + geometry-join rate under ONE unified caliber.

Grammar under test: header 12B = [u32 N][u32 tag][u32 0], N records of (tag+8) bytes,
record = f32[16] row-major affine + char name[stride-64].
"""
import collections
import glob
import os
import re
import sqlite3
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
TREE = r"D:\TLGL\.scratch\out\tree"
NAMEOK = re.compile(rb"^[A-Za-z0-9_\-.]{4,80}$")
EXTOK = re.compile(rb"^[A-Za-z0-9_\-.]{4,80}\.(mesh|tani|obj|bin|sco)$")


def mesh_valid(fp):
    """A's gate: file readable, >=0x94 bytes, u32 facecount @0x90 nonzero."""
    try:
        with open(fp, "rb") as fh:
            hd = fh.read(0x94)
    except OSError:
        return 0
    return struct.unpack_from("<I", hd, 0x90)[0] if len(hd) >= 0x94 else 0


def mat_ok(m):
    col = (m[3], m[7], m[11], m[15])
    if not (abs(col[0]) < 1e-5 and abs(col[1]) < 1e-5 and abs(col[2]) < 1e-5 and abs(col[3] - 1) < 1e-4):
        return False
    # row4 (m[12..14]) = translation, m[15]=1 -> already covered; reject all-zero/degenerate scale rows
    return any(abs(v) > 1e-30 for v in m[:12])


con = sqlite3.connect("file:D:/TLGL/.scratch/resources.db?mode=ro", uri=True)
db_scene_paths = [r[0] for r in con.execute("select path from resources where ext='.scene'")]
db_scene_named = [p for p in db_scene_paths if p]
db_mesh_named = set()
for (p,) in con.execute("select path from resources where ext='.mesh' and named=1"):
    if p:
        db_mesh_named.add(p.rsplit("/", 1)[-1].lower())
print(f"db: ext='.scene' rows={len(db_scene_paths)} with-path={len(db_scene_named)}  named .mesh basenames={len(db_mesh_named)}")

src_ok = set()
for d in os.listdir(os.path.join(TREE, "mobile_maps_source")):
    if d.lower().endswith(".mesh") and mesh_valid(os.path.join(TREE, "mobile_maps_source", d)):
        src_ok.add(d.lower())
print(f"tree mobile_maps_source: .mesh with nonzero facecount = {len(src_ok)}")

files = glob.glob(os.path.join(TREE, "mobile_maps", "*", "*.scene"))
print(f"tree .scene files on disk = {len(files)}")

cat = collections.Counter()
tag_hist = collections.Counter()
size_hist = collections.Counter()
tot = collections.Counter()          # unified counters
a_cal = collections.Counter()        # A caliber: NAMEOK records, tag 753/749 only
b_cal = collections.Counter()        # B caliber: N summed, stride hard 761, gate len>=64 and 12+761N<=len+761
maps = collections.defaultdict(lambda: [0, 0, 0])   # map -> [named instances, joined, all records]
bad_examples = []

for f in files:
    mp = os.path.basename(os.path.dirname(f))
    raw = open(f, "rb").read()
    size_hist[min(len(raw) // 4, 3)] += 1
    if len(raw) < 12:
        cat["tiny<12B (empty/placeholder)"] += 1
        continue
    N, tag, Z = struct.unpack_from("<III", raw, 0)
    tag_hist[tag] += 1
    if tag not in (753, 749):
        cat["other tag (set/copy/unknown)"] += 1
        if Z != 0:
            cat["  ^ with nonzero 3rd u32"] += 1
        continue
    cat["grid753/749 instance table"] += 1
    stride = tag + 8
    exp = 12 + stride * N - 8
    if exp != len(raw):
        size_off = len(raw) - exp
        if size_off not in (-8, 0, 8):
            cat["  ^ size != 12+stride*N-8 (other)"] += 1
    # ---- B caliber replay (stride fixed 761, its own gate)
    if len(raw) >= 64 and N and (12 + 761 * N <= len(raw) + 761):
        b_cal["files"] += 1
        b_cal["instances(N)"] += N
    # ---- unified per-record walk
    nrec = 0
    for i in range(N):
        off = 12 + stride * i
        if off + 64 > len(raw):
            break
        nrec += 1
        m = struct.unpack_from("<16f", raw, off)
        nb = raw[off + 64:off + stride].split(b"\x00", 1)[0]
        tot["records in-bounds"] += 1
        mo = mat_ok(m)
        if mo:
            tot["matrix ok"] += 1
        if not nb:
            tot["name empty"] += 1
            continue
        if not NAMEOK.match(nb):
            tot["name rejected (charset/len)"] += 1
            if len(bad_examples) < 6:
                bad_examples.append((f, i, nb[:40]))
            continue
        s = nb.decode("latin1").lower()
        a_cal["instances(A: NAMEOK records)"] += 1
        maps[mp][0] += 1
        if not mo:
            tot["  named but matrix bad"] += 1
        j = s in src_ok and s in db_mesh_named
        if j:
            tot["joined (name in db AND src file w/ faces)"] += 1
            maps[mp][1] += 1
        elif s in db_mesh_named:
            tot["  in db but src file unreadable/no faces"] += 1
        elif s in src_ok:
            tot["  src file ok but NOT named in db"] += 1
        else:
            tot["  name absent from both"] += 1
        if EXTOK.match(nb):
            tot["  name has .mesh/.tani/... ext"] += 1
        else:
            tot["  name without known ext"] += 1
            if len(bad_examples) < 12:
                bad_examples.append((f, i, nb[:40]))
    tot["records declared (sum N)"] += N
    tot["records walked"] += nrec
    if nrec != N:
        cat["  ^ N larger than walkable records"] += 1
    maps[mp][2] += nrec

print("\n=== file categories (%d .scene on disk) ===" % len(files))
for k, v in cat.most_common():
    print(f"  {k:48s} {v}")
print("  tag histogram top10:", tag_hist.most_common(10))
print("  size buckets (0=<4B,1=<8B,2=<12B,3=>=12B):", dict(size_hist))

print("\n=== unified record counters (grid753/749 files only) ===")
for k, v in tot.most_common():
    print(f"  {k:48s} {v:,}")

print("\n=== calibers ===")
print(f"  A caliber  instances={a_cal['instances(A: NAMEOK records)']:,}")
print(f"  B caliber  files={b_cal['files']:,} instances(N)={b_cal['instances(N)']:,}")
dec = tot["records declared (sum N)"]
inb = tot["records in-bounds"]
joined = tot["joined (name in db AND src file w/ faces)"]
namedrec = a_cal["instances(A: NAMEOK records)"]
print(f"  declared N total          = {dec:,}")
print(f"  in-bounds records         = {inb:,}")
print(f"  name-valid records        = {namedrec:,}  ({100*namedrec/dec:.2f}% of declared)")
print(f"  joined to real geometry   = {joined:,}")
print(f"  join rate / name-valid    = {100*joined/namedrec:.2f}%")
print(f"  join rate / in-bounds     = {100*joined/inb:.2f}%")
print(f"  join rate / declared      = {100*joined/dec:.2f}%")
print("\n  rejected-name examples:")
for f, i, nb in bad_examples:
    print(f"    {os.path.basename(os.path.dirname(f))}/{os.path.basename(f)} rec{i} {nb!r}")

rr = [(m, v[1] / max(1, v[0])) for m, v in maps.items() if v[0]]
buck = collections.Counter(">=99%" if q >= .99 else ">=95%" if q >= .95 else ">=80%" if q >= .8
                          else ">=50%" if q >= .5 else ">0%" if q > 0 else "0%" for m, q in rr)
print(f"\n  maps with >=1 named instance: {len(rr)} / dirs with .scene: {len(maps)}")
print("  per-map join-rate buckets:", dict(buck))
import statistics
print("  median per-map join rate: %.1f%%" % (100 * statistics.median(q for _, q in rr)))
