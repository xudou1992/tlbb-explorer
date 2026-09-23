"""Do the two header tags (753 vs 749) mean two record strides? Measure name->name gaps."""
import re
import sqlite3
import struct
from collections import Counter
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree")
con = sqlite3.connect("file:resources.db?mode=ro", uri=True)
paths = [r[0] for r in con.execute(
    "SELECT path FROM resources WHERE lower(path) LIKE '%.scene' AND path IS NOT NULL")]
byname = Counter()
rows = {}
for rel in paths:
    f = TREE / rel
    if not f.exists():
        continue
    raw = f.read_bytes()
    if len(raw) < 64:
        continue
    n0, tag = struct.unpack_from("<2I", raw, 0)
    if tag not in (749, 753, 757, 761):
        byname[f"tag={tag}"] += 1
        continue
    occ = [m.start() for m in re.finditer(rb"[ -~]{3,80}?\.(?:mesh|tani)\x00", raw)]
    gaps = Counter(occ[i + 1] - occ[i] for i in range(len(occ) - 1))
    top = gaps.most_common(1)[0] if gaps else (0, 0)
    fit = (len(raw) - 12) / n0 if n0 else 0
    rows.setdefault(tag, []).append((top[0], round(fit, 2), n0, len(occ)))
    byname[f"tag={tag}"] += 1

print("文件计数:", dict(byname))
for tag, v in sorted(rows.items()):
    g = Counter(x[0] for x in v)
    fits = [x[1] for x in v]
    print(f"\ntag={tag}  n={len(v)}  名字间距众数={g.most_common(3)}  "
          f"(size-12)/N 中位数≈{sorted(fits)[len(fits)//2]:.2f}")
    for want in (761, 757, 753, 749):
        hits = sum(1 for x in v if x[0] == want)
        print(f"    间距=={want}: {hits}/{len(v)}")
