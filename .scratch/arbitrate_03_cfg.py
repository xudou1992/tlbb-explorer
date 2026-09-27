"""Arbitration step 3: ResourcePath.cfg -- is it decodable, how many paths, can it name the
.scene geometry that resources.db lost?  Read-only."""
import collections
import os
import re
import sqlite3
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\TLGL\.scratch")
HERE = r"D:\TLGL\.scratch"
raw = open(os.path.join(HERE, "out", "tree", "ResourcePath.cfg"), "rb").read()
BLOB_S, BLOB_E = 3783792, 10853869
blob = raw[BLOB_S:BLOB_E]
hdr = struct.unpack_from("<24I", raw, 0)
print(f"cfg bytes={len(raw)}  magic={raw[:4]!r}  version={hdr[2]}  hdr[3]=size-16={hdr[3]==len(raw)-16}")
print("header u32[0:24]:", hdr)

# ---- hunt for a 72,764-entry offset array inside [52, BLOB_S)
CAND = hdr[9]
print(f"\nhdr[9]={CAND}   hdr[10]={hdr[10]}  hdr[10]/hdr[9]={hdr[10]/CAND:.4f}  hdr[9]*9={CAND*9}")
for C in (CAND,):
    for stride in (4, 8, 9, 12, 16, 20, 36):
        span = C * stride
        if span > len(raw) - 52:
            continue
        # try every plausible start in the low region (sampled)
        hits = 0
        best = None
        for st in range(52, 52 + 200):
            vals = struct.unpack_from(f"<{min(C, 50)}I", raw, st) if stride == 4 else None
            if vals and all(0 <= v < len(blob) for v in vals) and list(vals) == sorted(vals):
                best = (st, vals[:6])
                break
        print(f"  stride {stride}: early-header monotonic u32 fit -> {best}")

# ---- prefix inventory of the string blob
PREF = [b"mobile_maps_source/", b"mobile_maps/", b"data/", b"ui/", b"scripts/", b"settings/", b"engine/"]
pos = []
for p in PREF:
    s = 0
    while True:
        i = blob.find(p, s)
        if i < 0:
            break
        pos.append((i, p))
        s = i + 1
pos.sort()
print(f"\nprefix hits in blob: {len(pos)}  by prefix:",
      {p.decode(): sum(1 for _, q in pos if q == p) for p in PREF})
# inflation: a prefix hit that is itself preceded by '/' is an INNER component, not a record start
inner = [i for i, p in pos if i and blob[i - 1:i] == b"/"]
print(f"  of those, preceded by '/' (inner path component, not a record start): {len(inner)}")
starts = [i for i, p in pos if not (i and blob[i - 1:i] == b"/")]
print(f"  => candidate record starts: {len(starts)}")
# what precedes each record start (end of the previous key)
pre = collections.Counter()
for i in starts:
    seg = blob[max(0, i - 40):i]
    m = re.search(rb"\.([A-Za-z0-9]{1,10})$", seg)
    pre[m.group(1).decode() if m else "(no-ext)"] += 1
print("  extension of the string immediately before each record start (= key ext) top12:", pre.most_common(12))

# ---- reconstruct (key, path) pairs by walking starts forward with extension-rule
PATH = re.compile(rb"(?:mobile_maps_source|mobile_maps|data|ui|scripts|settings|engine)/"
                  rb"[A-Za-z0-9_\-\./]*?/[A-Za-z0-9_\-\.\+]{1,120}?\.[A-Za-z0-9]{1,8}")
paths = []
i = 0
S = starts
for k, s in enumerate(S):
    e_bound = S[k + 1] if k + 1 < len(S) else len(blob)
    m = PATH.match(blob, s)
    if m and m.end() <= e_bound:
        paths.append(m.group())
    else:
        paths.append(None)
bad = sum(1 for p in paths if p is None)
print(f"\ngreedy regex paths: {len(paths)-bad:,} parsed, {bad:,} failed")
ok = [p for p in paths if p]
print(f"  distinct paths: {len(set(p.lower() for p in ok)):,}")
print(f"  ext histogram:", collections.Counter(p.rsplit(b'.', 1)[-1].decode(errors='replace') for p in ok).most_common(12))
# key/path pairing sanity: does the key right before each path occur as the path basename?
hit = sum(1 for p in ok if p.rsplit(b'/', 1)[-1] in blob or True)

# ---- db cross-check
con = sqlite3.connect("file:D:/TLGL/.scratch/resources.db?mode=ro", uri=True)
dbpath = {p.lower() for (p,) in con.execute("select path from resources where named=1 and path is not null")}
allhash = {h for (h,) in con.execute("select hash from resources")}
namedhash = {h for (h,) in con.execute("select hash from resources where named=1")}
print(f"\ndb: rows(named=1,path)={len(dbpath):,}  total hashes={len(allhash):,}  named hashes={len(namedhash):,}")
low = [p.decode("latin1").lower() for p in ok]
in_db = sum(1 for p in low if p in dbpath)
print(f"cfg paths found verbatim in db.path: {in_db:,} / {len(low):,} = {100*in_db/max(len(low),1):.2f}%")

# ---- the DECISIVE test: hash cfg paths and see whether they hit UNNAMED db rows
import numpy  # noqa
from mine2 import batch_hash
toks = [p.encode("latin1") for p in ok]
byname = {}
for L in (160,):
    hs = batch_hash(toks, L)
    for t, h in zip(toks, hs):
        byname[t.decode('latin1')] = "%016x" % int(h)
hit_all = hit_un = 0
un_examples = []
for p, h in byname.items():
    if h in allhash:
        hit_all += 1
        if h not in namedhash:
            hit_un += 1
            if len(un_examples) < 8:
                un_examples.append((p, h))
print(f"\nhash(batch_hash(path,160)) hits a db row: {hit_all:,}/{len(byname):,} = {100*hit_all/max(len(byname),1):.2f}%")
print(f"  ... and that row is currently UNNAMED (i.e. a name we can hand back): {hit_un:,}")
for p, h in un_examples:
    print("   ", h, p)
