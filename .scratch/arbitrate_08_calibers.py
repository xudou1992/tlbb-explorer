"""Arbitration: (a) replay B's exact caliber, (b) quantify the parts BOTH sides missed --
the unnamed scene/grid753 tables that never landed in out/tree but exist as blobs."""
import collections
import glob
import os
import re
import sqlite3
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = r"D:\TLGL\.scratch"
TREE = os.path.join(HERE, "out", "tree")
con = sqlite3.connect("file:D:/TLGL/.scratch/resources.db?mode=ro", uri=True)
NAME = re.compile(rb"^[ -~]{3,80}?\.(mesh|tani)$")
NAMEOK = re.compile(rb"^[A-Za-z0-9_\-.]{4,80}$")

# ---------- (a) faithful replay of agent_scene_cover.py ----------
paths = [r[0] for r in con.execute("SELECT path FROM resources WHERE lower(path) LIKE '%.scene' AND path IS NOT NULL")]
maps = {}
for p in paths:
    s = p.split("/")
    if len(s) > 2 and s[0] == "mobile_maps":
        maps.setdefault(s[1], []).append(p)
files = inst = inst_ok = blank = badmat = skipped = 0
for mp, rels in maps.items():
    for rel in rels:
        f = os.path.join(TREE, *rel.split("/"))
        if not os.path.exists(f):
            skipped += 1
            continue
        raw = open(f, "rb").read()
        if len(raw) < 64:
            continue
        N = struct.unpack_from("<I", raw, 0)[0]
        if not N or 12 + 761 * N > len(raw) + 761:
            continue
        good = 0
        for i in range(N):
            off = 12 + 761 * i
            if off + 761 > len(raw):
                break
            m = struct.unpack_from("<16f", raw, off)
            col = (m[3], m[7], m[11], m[15])
            if not (all(abs(c) < 1e-5 for c in col[:3]) and abs(col[3] - 1) < 1e-4):
                badmat += 1
                continue
            nb = raw[off + 64: off + 761].split(b"\x00")[0]
            if not nb:
                blank += 1
            elif NAME.match(nb):
                good += 1
        files += 1
        inst += N
        inst_ok += good
print("=== (a) B caliber replayed verbatim (stride hard-coded 761, gate = its own) ===")
print(f"  maps={len(maps)} files={files:,} instances(N)={inst:,} name-plausible={inst_ok:,} "
      f"= {100*inst_ok/max(inst,1):.2f}%  matrix-bad={badmat:,} empty-name={blank:,} "
      f"missing-on-disk={skipped:,}")

# ---------- (b) the tables that never landed in tree ----------
q = list(con.execute("select hash,subtype,original from resources where named=0 and "
                     "(type='scene' or subtype like '%grid%' or ext='.scene')"))
print(f"\n=== (b) unnamed scene-ish db rows: {len(q)} ===")
allblobs = {}
for p in glob.glob(os.path.join(HERE, "out", "all", "*", "*")):
    allblobs[os.path.basename(p).split(".")[0]] = p
print(f"  blobs available under out/all: {len(allblobs):,}")
tot_b = collections.Counter()
tagc = collections.Counter()
stride_c = collections.Counter()
missing = 0
for h, sub, orig in q:
    f = allblobs.get(h)
    if not f:
        missing += 1
        continue
    raw = open(f, "rb").read()
    if len(raw) < 12:
        tot_b["blob<12B"] += 1
        continue
    N, tag, z = struct.unpack_from("<III", raw, 0)
    tagc[tag] += 1
    if tag not in (753, 749):
        tot_b["blob other tag"] += 1
        continue
    stride_c[tag] += 1
    st = tag + 8
    rec = 0
    named = 0
    for i in range(N):
        o = 12 + st * i
        if o + 64 > len(raw):
            break
        rec += 1
        nb = raw[o + 64:o + st].split(b"\x00", 1)[0]
        if nb and NAMEOK.match(nb):
            named += 1
    tot_b["declared N"] += N
    tot_b["in-bounds records"] += rec
    tot_b["name-valid records"] += named
print(f"  rows with no blob on disk: {missing:,}")
print("  tag histogram:", tagc.most_common(6))
print("  grid753/749 files found:", dict(stride_c))
print("  their records:", dict(tot_b))

# ---------- (c) size-law check over the tree files (is A's grammar universal?) ----------
d = collections.Counter()
off_hist = collections.Counter()
n = 0
for f in glob.glob(os.path.join(TREE, "mobile_maps", "*", "*.scene")):
    raw = open(f, "rb").read()
    if len(raw) < 12:
        continue
    N, tag, z = struct.unpack_from("<III", raw, 0)
    if tag not in (753, 749) or not N:
        continue
    n += 1
    off_hist[len(raw) - (12 + (tag + 8) * N)] += 1
print(f"\n=== (c) size law over {n:,} grid files: size-(12+stride*N) histogram top8 ===")
print("  ", off_hist.most_common(8))
print(f"  exactly -8: {off_hist[-8]:,} ({100*off_hist[-8]/n:.1f}%)  "
      f"|delta|<=8: {sum(v for k, v in off_hist.items() if abs(k) <= 8):,} ({100*sum(v for k,v in off_hist.items() if abs(k)<=8)/n:.1f}%)")
