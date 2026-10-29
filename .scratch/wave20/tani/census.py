"""Read-only census of .tani / GATA. Writes stats next to this script."""
import collections
import json
import os
import sqlite3
import struct
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree")
DB = r"D:\TLGL\.scratch\resources.db"
OUT = Path(__file__).resolve().parent

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

print("=== catalog ===")
q = """
select ext, type, subtype, count(*) n, min(original) mn, max(original) mx, sum(original) sm
from resources
where ext='.tani' or type='GATA' or path like '%.tani'
group by 1,2,3
"""
for r in con.execute(q):
    print(dict(r))

print("--- dirs ---")
for r in con.execute(
    "select dir, count(*) n from resources where ext='.tani' group by 1 order by 2 desc"
):
    print(dict(r))

print("GATA not .tani", con.execute(
    "select count(*) from resources where type='GATA' and ifnull(ext,'')!='.tani'"
).fetchone()[0])
print("tani not GATA", con.execute(
    "select count(*) from resources where ext='.tani' and ifnull(type,'')!='GATA'"
).fetchone()[0])
print("path-null tani", con.execute(
    "select count(*) from resources where ext='.tani' and path is null"
).fetchone()[0])

rows = list(con.execute(
    "select hash, path, name, ext, type, subtype, original, props "
    "from resources where ext='.tani' order by original, path"
))
print("db .tani rows", len(rows))

# disk
disk = {}
for p in TREE.rglob("*.tani"):
    disk[p.relative_to(TREE).as_posix().lower()] = p
print("disk *.tani", len(disk))

missing = []
extra_disk = set(disk)
size_mismatch = []
magic = collections.Counter()
u32_4 = collections.Counter()
sizes = []
path_kind = collections.Counter()  # full virtual vs bare name vs other
pad_bad = 0
align_hist = collections.Counter()  # body start % 16
nul_ok = 0
no_nul = 0
path_eq_name = 0
path_eq_rel = 0
ani_banner = 0
jbcf_shape = 0
jbpu_shape = 0
min2 = 0
copyright = 0
samples = []  # smallest 8 and a few mid

bodies = []  # (relpath, data, body_off)

for r in rows:
    rel = (r["path"] or "").replace("\\", "/")
    p = disk.get(rel.lower())
    if p is None:
        # try name-only under data/tani
        alt = TREE / "data" / "tani" / (r["name"] or "")
        p = alt if alt.is_file() else None
    if p is None:
        missing.append(rel or r["hash"])
        continue
    extra_disk.discard(rel.lower())
    b = p.read_bytes()
    if r["original"] is not None and len(b) != r["original"]:
        size_mismatch.append((rel, len(b), r["original"]))
    sizes.append(len(b))
    magic[b[:4]] += 1
    if b[:10] == b"Copyright ":
        copyright += 1
    if b[:4] == b"JBCF":
        jbcf_shape += 1
    if b[:4] == b"JBPU":
        jbpu_shape += 1
    if b"MIN2" in b[:0x100]:
        min2 += 1
    if len(b) >= 0x44 and b[0x40:0x43] == b"ani":
        ani_banner += 1
    if len(b) >= 8:
        u32_4[struct.unpack_from("<I", b, 4)[0]] += 1
    z = b.find(b"\x00", 8)
    if z < 0 or z > 400:
        no_nul += 1
        continue
    nul_ok += 1
    s = b[8:z].decode("latin1")
    name = r["name"] or ""
    if s == name or s.endswith("/" + name) or s == rel:
        path_eq_name += 1
    if s == rel or s.lower() == rel.lower():
        path_eq_rel += 1
        path_kind["equals-db-path"] += 1
    elif s.endswith(".tani") and "/" not in s and "\\" not in s:
        path_kind["bare-filename"] += 1
    elif s.endswith(".tani"):
        path_kind["other-path"] += 1
    else:
        path_kind["not-tani-string"] += 1
    # alignment of first byte after NUL
    nxt = z + 1
    # find pad
    pad = b[nxt:nxt + 16]
    # body candidates: align4 and align8
    a4 = (nxt + 3) & ~3
    a8 = (nxt + 7) & ~7
    align_hist[f"a4={a4 - nxt} a8={a8 - nxt} mod16={a4 & 15}"] += 1
    # padding between nul+1 and a8 must be 0 for a clean align
    if b[nxt:a8] != b"\x00" * (a8 - nxt):
        pad_bad += 1
    bodies.append((rel, b, a8, s))

print("missing disk", len(missing), missing[:5])
print("disk not in db paths", len(extra_disk), list(extra_disk)[:5])
print("size mismatch", len(size_mismatch), size_mismatch[:5])
print("magic", {k: v for k, v in magic.items()})
print("u32@4 top", u32_4.most_common(8), "distinct", len(u32_4))
print("copyright", copyright, "ani@0x40", ani_banner, "MIN2 in first 0x100", min2)
print("jbcf magic", jbcf_shape, "jbpu magic", jbpu_shape)
print("nul_ok", nul_ok, "no_nul", no_nul)
print("path matches name-or-rel", path_eq_name, "path equals db path", path_eq_rel)
print("path kind", path_kind)
print("pad to a8 not zero", pad_bad)
print("align hist", align_hist.most_common(12))

# size distribution
sizes.sort()
buckets = [(0, 256), (256, 512), (512, 1024), (1024, 2048), (2048, 4096),
           (4096, 8192), (8192, 16384), (16384, 32768), (32768, 10**9)]
print("n", len(sizes), "min", sizes[0] if sizes else None, "max", sizes[-1] if sizes else None,
      "sum", sum(sizes))
print("p50", sizes[len(sizes)//2] if sizes else None,
      "p90", sizes[int(len(sizes)*0.9)] if sizes else None)
for lo, hi in buckets:
    c = sum(1 for s in sizes if lo <= s < hi)
    print(f"  [{lo},{hi}) {c}")
# multiples
print("mod 4", sum(1 for s in sizes if s % 4 == 0), "/", len(sizes))
print("mod 8", sum(1 for s in sizes if s % 8 == 0), "/", len(sizes))
print("mod 16", sum(1 for s in sizes if s % 16 == 0), "/", len(sizes))

# JBCF invariants on tani bytes
inv = collections.Counter()
for rel, b, a8, s in bodies:
    n = len(b)
    if n >= 24:
        u = struct.unpack_from("<6I", b, 0)
        inv["u32@4==0"] += u[1] == 0
        inv["u32@8==8"] += u[2] == 8
        inv["u32@12==size-16"] += u[3] == n - 16
        inv["u32@16==86"] += u[4] == 86
    if n >= 0x100:
        inv["has Copyright"] += b[:10] == b"Copyright "
        inv["tag ani at 0x40"] += b[0x40:0x44] == b"ani\x00"
        inv["MIN2 at 0x8C"] += b[0x8C:0x90] == b"MIN2"
print("ani/jbcf invariant hits", inv, "of", len(bodies))

# body first u64 histogram-ish: classify words after a8
cls = collections.Counter()
first_u32 = collections.Counter()
ptr_like = 0
words = 0
hi_hist = collections.Counter()
# also record body length
blen = collections.Counter()
for rel, b, a8, s in bodies:
    body = b[a8:]
    blen[len(body) % 8] += 1
    if len(body) < 8:
        cls["short-body"] += 1
        continue
    # scan u64
    nq = len(body) // 8
    for i in range(nq):
        v = struct.unpack_from("<Q", body, i * 8)[0]
        words += 1
        hi = v >> 32
        if v == 0:
            cls["zero"] += 1
        elif hi == 0 and v < 0x10000:
            cls["small"] += 1
        elif hi == 0:
            cls["u32ish"] += 1
        elif 0x10000 <= hi <= 0x7FFFFFFF:
            cls["user-ptr"] += 1
            ptr_like += 1
            hi_hist[f"{hi:08x}"[:4]] += 1
        elif hi >= 0xFFFF0000:
            cls["neg"] += 1
        else:
            cls["other"] += 1
    u0 = struct.unpack_from("<I", body, 0)[0]
    first_u32[u0 if u0 < 64 else "ge64"] += 1

print("body len % 8", blen)
print("u64 classes", cls, "words", words, "ptr", ptr_like)
print("hi16 of user-ptr top", hi_hist.most_common(12))
print("first u32 of a8-body", first_u32.most_common(15))

# save a compact json of per-file header facts for the next pass
facts = []
for rel, b, a8, s in bodies:
    facts.append({
        "path": rel,
        "n": len(b),
        "str": s,
        "a8": a8,
        "body": len(b) - a8,
    })
(OUT / "headers.json").write_text(json.dumps({
    "n": len(bodies),
    "missing": len(missing),
    "magic": {k.hex(): v for k, v in magic.items()},
    "sizes": {"n": len(sizes), "min": min(sizes), "max": max(sizes), "sum": sum(sizes)},
}, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote headers.json facts", len(facts))
# also dump 6 smallest full hex later in probe2
smallest = sorted(bodies, key=lambda t: len(t[1]))[:6]
largest = sorted(bodies, key=lambda t: -len(t[1]))[:2]
(OUT / "samples_idx.txt").write_text(
    "\n".join(f"{len(b):6d} a8={a8:4d} {rel} str={s!r}" for rel, b, a8, s in smallest + largest),
    encoding="utf-8",
)
print("smallest:")
for rel, b, a8, s in smallest:
    print(f"  {len(b):6d} a8={a8} {rel}")
