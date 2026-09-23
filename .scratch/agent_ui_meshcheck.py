"""只读：把「面板会出现」的 1,659 组的首个可定位网格，逐个跑一遍与
crates/core/src/preview/geometry.rs::parse_geometry 等价的 Python 判定，
统计「走到 3D 面板但后端解析失败」到底多少条。

不写库、不改源码。输出 D:\TLGL\.scratch\agent_ui_mesh.txt (UTF-8)
"""
import os
import sqlite3
import struct
from collections import Counter, defaultdict
from pathlib import Path

DB = r"file:D:/TLGL/.scratch/resources.db?mode=ro"
TREE = Path(r"D:\TLGL\.scratch\out\tree")
MAX = 8_000_000
out = []
def w(s=""): out.append(str(s))

con = sqlite3.connect(DB, uri=True)

res = {}
for h, p, n, e in con.execute("select hash, path, name, ext from resources"):
    cur = res.get(h)
    if cur is None or (not cur[0] and p):
        res[h] = (p or "", n or "", e or "")
members = defaultdict(list)
for gid, h, role in con.execute("select gid, hash, role from amembers"):
    members[gid].append((role, h))
refs_by = defaultdict(list)
for fh, n, k, th in con.execute("select from_hash, name, kind, to_hash from refs"):
    refs_by[fh].append((n, k, th))
groups = {r[0]: r for r in con.execute("select id, stem, kind, n, n_mesh from agroups")}


def u32(b, off):
    return struct.unpack_from("<I", b, off)[0] if off + 4 <= len(b) else None


def locate(raw, lo, fc, vc):
    need = 4 + fc * 3 * 2
    if fc == 0 or len(raw) < need:
        return None
    hi = len(raw) - need
    want = struct.pack("<I", fc)
    at = lo
    while at <= hi:
        p = raw.find(want, at, hi + 4)
        if p < 0:
            return None
        blk = raw[p + 4: p + need]
        if all(struct.unpack_from("<H", blk, i)[0] < vc for i in range(0, len(blk), 2)):
            return p
        at = p + 4
    return None


def verdict(raw):
    n = len(raw)
    if n < 0x118:
        return "文件只有 %d 字节，连几何头（0x118）都不够" % n, None
    vc, fc, sm = u32(raw, 0x8C), u32(raw, 0x90), u32(raw, 0x94)
    meta = {"vc": vc, "fc": fc, "sm": sm, "size": n}
    if vc is None or fc is None or vc > MAX or fc > MAX:
        return "头部计数不合理，拒绝解析", meta
    pos_end = 0x118 + vc * 12
    if pos_end > n:
        return "几何数据在 %#x 处截断" % pos_end, meta
    static_idx = pos_end + vc * 20
    idx = static_idx if u32(raw, static_idx) == fc else locate(raw, pos_end, fc, vc)
    if idx is None:
        return "找不到与头部面数 %s 自洽的索引块——拒绝解析" % fc, meta
    return None, meta


first_stats = Counter()
fail_examples = []
pathless = 0
not_in_tree = []
reachable = 0
sm_hist = Counter()
fail_by_kind = Counter()
all_mesh_refs = Counter()

for gid, r in groups.items():
    _id, stem, kind, n, n_mesh = r
    rows = sorted([(ro, res.get(h, ("", "", ""))[0], h) for ro, h in members.get(gid, [])],
                  key=lambda x: (x[0], x[1]))
    mdl = next(((p, h) for (_ro, p, h) in rows if p.lower().endswith(".mdl")), None)
    if mdl is None:
        continue
    mr = [(nm, th) for (nm, k, th) in refs_by.get(mdl[1], []) if k == ".mesh"]
    resolved = [x for x in mr if x[1]]
    if not resolved:
        continue
    reachable += 1
    # 所有 bodies（不止第一个）里定位到的网格，逐个数 sm
    for nm, th in resolved:
        sm_hist[None] += 0
    nm, th = resolved[0]
    p = res.get(th, ("", "", ""))[0]
    if not p:
        pathless += 1
        first_stats["D1 网格有 hash 但清单无 path（用 hash 取字节，tree 里无法核对）"] += 1
        continue
    f = TREE / p.replace("/", os.sep)
    if not f.exists():
        not_in_tree.append(p)
        first_stats["D4 tree 里找不到该实体文件"] += 1
        continue
    err, meta = verdict(f.read_bytes())
    if err:
        first_stats["D3 后端 mesh_data 解析失败 → 「这个模型暂时画不出来」"] += 1
        fail_by_kind[kind] += 1
        if len(fail_examples) < 12:
            fail_examples.append((gid, stem, kind, p, meta, err))
    else:
        first_stats["D2 正常出灰模"] += 1
    if meta:
        sm_hist[meta["sm"]] += 1

w(f"面板会出现的组（重复 v1 口径核对）：{reachable}")
w("=== 首帧自动加载的那个网格的结果 ===")
for k, v in first_stats.most_common():
    w(f"  {k:66s} {v:6d}  {v*100.0/max(reachable,1):5.1f}%")
w("")
w(f"  失败按类型：{fail_by_kind.most_common()}")
w(f"  失败样本的 sm（子网格数 0x94）分布：{Counter(x[4]['sm'] for x in fail_examples).most_common()}")
w("  失败样本：")
for gid, stem, kind, p, meta, err in fail_examples:
    w(f"   gid={gid} {stem} [{kind}] {p}")
    w(f"      {err}  meta={meta}")
w("")
w(f"tree 里找不到的路径样本（最多 8）：{not_in_tree[:8]}")
w("")
w("=== 全量：所有被 .mdl 引用且定位到的网格文件（去重按文件） ===")
files = Counter()
fails = Counter()
seen = set()
for gid in groups:
    pass
for fh, lst in refs_by.items():
    for nm, k, th in lst:
        if k != ".mesh" or not th:
            continue
        p = res.get(th, ("", "", ""))[0]
        if not p or p in seen:
            continue
        seen.add(p)
        f = TREE / p.replace("/", os.sep)
        if not f.exists():
            files["tree 缺失"] += 1
            continue
        err, meta = verdict(f.read_bytes())
        files["失败" if err else "可画"] += 1
        if err:
            fails[meta["sm"]] += 1
w(f"  被 .mdl 引用且名字定位到实体的 .mesh（有 path、去重）：{sum(files.values())} → {dict(files)}")
w(f"  其中解析失败文件的 sm 分布：{fails.most_common(12)}")

Path(r"D:\TLGL\.scratch\agent_ui_mesh.txt").write_text("\n".join(out), encoding="utf-8")
print("written")
