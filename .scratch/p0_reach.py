"""p0_reach.py —— 只读：工作台真实入口下的「立体模型」许诺面有多大，
以及这些被 .mdl 引用且解出 hash 的网格，走 AppData::mesh_geometry 这一路
（hash → 资源行 → 从 .pak 读字节 → parse_geometry）有哪几处会翻车。

判定表用现成编译好的 mesh_gate.exe 产物 p0_gate.tsv（Rust 当前解析器原样跑的）。
"""
import os
import sqlite3
from collections import Counter, defaultdict

DB = r"file:D:/TLGL/.scratch/resources.db?mode=ro"
TREE = r"D:\TLGL\.scratch\out\tree"
con = sqlite3.connect(DB, uri=True)

# 解析判定（path -> (ok, err, sm, vc, fc)）
verdict = {}
for line in open(r"D:\TLGL\.scratch\p0_gate.tsv", encoding="utf-8", errors="replace"):
    p = line.rstrip("\n").split("\t")
    if len(p) < 3:
        continue
    rel = p[0].replace("\\", "/")
    if p[1] == "OK":
        verdict[rel] = (True, "", int(p[5]), int(p[3]), int(p[4]))
    else:
        verdict[rel] = (False, p[2], None, None, None)
print("gate rows:", len(verdict), "失败:", sum(1 for v in verdict.values() if not v[0]))

res = {}
for h, p, n, e, pk in con.execute("select hash, path, name, ext, pak from resources"):
    cur = res.get(h)
    if cur is None or (not cur[0] and p):
        res[h] = (p or "", n or "", e or "", pk or "")
rec = defaultdict(list)
for h, pk, o, oc in con.execute("select hash, pak, offset, occupied from records"):
    rec[h].append((pk, o, oc))
refs_by = defaultdict(list)
for fh, n, k, th in con.execute("select from_hash, name, kind, to_hash from refs"):
    refs_by[fh].append((n, k, th))
members = defaultdict(list)
for gid, h, role in con.execute("select gid, hash, role from amembers"):
    members[gid].append((role, h))
groups = {r[0]: r for r in con.execute("select id, stem, kind, n, n_mesh from agroups")}

n_promise = 0
slot_mesh_hash_total = 0
slot_unreadable = Counter()
first_slot_bad = 0
all_slot_bad = 0
reachable_files = {}
ext_seen = Counter()
kind_promise = Counter()
by_pak = Counter()

for gid, (_id, stem, kind, n, n_mesh) in groups.items():
    mdl = next(((h,) for role, h in sorted(members.get(gid, []), key=lambda x: x[1])
                if res.get(h, ("",))[0].lower().endswith(".mdl")), None)
    if mdl is None:
        continue
    mr = [(nm, th) for (nm, k, th) in refs_by.get(mdl[0], []) if k == ".mesh" and th]
    if not mr:
        continue
    n_promise += 1
    kind_promise[kind] += 1
    oks = []
    for nm, th in mr:
        slot_mesh_hash_total += 1
        p, name, ext, pk = res.get(th, ("", "", "", ""))
        ext_seen[ext] += 1
        by_pak[pk] += 1
        why = None
        if not p:
            why = "清单里没路径"
        elif not rec.get(th):
            why = "records 表里没这条（pak 里读不到）"
        elif not os.path.exists(os.path.join(TREE, p.replace("/", os.sep))):
            why = "解包树里没实体"
        elif p not in verdict:
            why = "gate 表里没有这条路径（未判定）"
        elif not verdict[p][0]:
            why = "parse_geometry 失败"
        if why:
            slot_unreadable[why] += 1
        oks.append(why is None)
        reachable_files[p] = why is None
    if not any(oks):
        all_slot_bad += 1
    if oks and not oks[0]:
        first_slot_bad += 1

print(f"会许诺「可以画」的组：{n_promise}")
print(f"  按类型：{kind_promise.most_common()}")
print(f"  这些组里带 hash 的网格槽位总数：{slot_mesh_hash_total}")
print(f"  槽位 ext 分布：{ext_seen.most_common()}")
print(f"  槽位所在容器分布：{by_pak.most_common()}")
print(f"  走不通的槽位原因：{dict(slot_unreadable) or '无'}")
print(f"  首帧自动加载那个网格走不通的组：{first_slot_bad}")
print(f"  所有网格槽位都走不通的组：{all_slot_bad}")
print(f"  可达 .mesh 文件（按路径去重）：{len(reachable_files)}，"
      f"其中解析失败 {sum(1 for v in reachable_files.values() if not v)}")

# 反查：有 mesh 成员、但没有 .mdl 的组（这些走 else-if 分支，写「还没解出」）
no_mdl_with_mesh = sum(1 for gid, g in groups.items()
                       if g[4] and not any(res.get(h, ("",))[0].lower().endswith(".mdl")
                                           for _r, h in members.get(gid, [])))
print(f"  对照组：有网格文件但没有 .mdl 的组（那一行走「还没解出」）：{no_mdl_with_mesh}")
print(f"  全部组数：{len(groups)}")
