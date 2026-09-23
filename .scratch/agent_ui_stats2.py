"""只读统计 v2：一次性把 resources/amembers/refs 读进内存，避免每组一次全表扫。

sqlite 以 mode=ro 打开；不写库、不改源码。
输出：D:\TLGL\.scratch\agent_ui_stats.txt (UTF-8)
"""
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

DB = r"file:D:/TLGL/.scratch/resources.db?mode=ro"
OUT = Path(r"D:\TLGL\.scratch\agent_ui_stats.txt")

con = sqlite3.connect(DB, uri=True)
out = []
def w(s=""): out.append(str(s))

TOTAL = con.execute("select count(*) from agroups").fetchone()[0]
w(f"总资产组 agroups = {TOTAL}")
w(f"amembers = {con.execute('select count(*) from amembers').fetchone()[0]}")
w(f"resources 行 = {con.execute('select count(*) from resources').fetchone()[0]} / distinct hash = "
  f"{con.execute('select count(distinct hash) from resources').fetchone()[0]}")
w(f"refs 行 = {con.execute('select count(*) from refs').fetchone()[0]}")
w("")

# hash -> (path, name, ext)；同 hash 多行时优先有 path 的（与 inspector 的 LIMIT 1 同效，
# 只是把「先拿到有路径的那行」固定下来，避免随机）
res = {}
for h, p, n, e, pak in con.execute("select hash, path, name, ext, pak from resources"):
    cur = res.get(h)
    if cur is None or (not cur[0] and p):
        res[h] = (p or "", n or "", e or "", pak or "")

members = defaultdict(list)
for gid, h, role in con.execute("select gid, hash, role from amembers"):
    members[gid].append((role, h))

refs_by = defaultdict(list)
for fh, n, k, th in con.execute("select from_hash, name, kind, to_hash from refs"):
    refs_by[fh].append((n, k, th))

groups = {r[0]: r for r in con.execute(
    "select id, stem, kind, n, n_mesh, n_mtl, n_ske, n_ani, n_tex, hub from agroups")}

bucket = Counter()
kinds_of_bucket = defaultdict(Counter)
examples = {}
first_mesh_by_gid = {}
resolved_cnt = Counter()
mesh_ref_total = Counter()

for gid, r in groups.items():
    _id, stem, kind, n, n_mesh, n_mtl, n_ske, n_ani, n_tex, hub = r
    # inspector.rs:423 members() 按 (role, path) 排序后取第一个 path 以 .mdl 结尾的成员
    rows = []
    for role, h in members.get(gid, []):
        path = res.get(h, ("", "", "", ""))[0]
        rows.append((role, path, h))
    rows.sort(key=lambda x: (x[0], x[1]))
    mdl = next(((p, h) for (_ro, p, h) in rows if p.lower().endswith(".mdl")), None)

    if mdl is None:
        mdl_named = [h for (_ro, p, h) in rows if res.get(h, ("", "", "", ""))[2] == ".mdl"]
        mdl_nopath = [h for h in mdl_named if not res.get(h, ("", "", "", ""))[0]]
        if mdl_nopath:
            b = "A2 组内有 .mdl 成员、文件也在客户端里，但清单里没 path → mdl=null"
        elif mdl_named:
            b = "A3 组内有 .mdl 成员但 resources 无 path 列值"
        elif n_mesh or n_ske or n_mtl:
            b = "A1b 组记着网格/骨骼/材质计数却没有任何 .mdl 主体成员 → mdl=null"
        else:
            b = "A1a 组里没有模型类文件（贴图/特效/场景/其它）→ mdl=null"
        bucket[b] += 1
        kinds_of_bucket[b][kind] += 1
        examples.setdefault(b, (gid, stem, kind, n, n_mesh, len(members.get(gid, []))))
        continue

    mhash = mdl[1]
    mr = [(n2, th) for (n2, k, th) in refs_by.get(mhash, []) if k == ".mesh"]
    sk = [(n2, th) for (n2, k, th) in refs_by.get(mhash, []) if k == ".ske"]
    resolved = [x for x in mr if x[1]]
    if not mr and not [x for x in sk if x[1]]:
        b = "B mdl 解不出任何组成成员（refs 里 .mesh/.ske 都没有）"
    elif not mr:
        b = "B2 mdl 只带骨骼引用 → 组成树只剩「骨骼 …」那一行，面板不出现"
    elif not resolved:
        b = "C mdl 有 .mesh 引用但一个都没定位到实体（mesh.hash 全空）→ 面板不出现"
    else:
        b = "D 面板会出现（≥1 个网格定位到）"
        first_mesh_by_gid[gid] = resolved[0][0]
        resolved_cnt[len(resolved)] += 1
    mesh_ref_total[(b, len(mr))] += 1
    bucket[b] += 1
    kinds_of_bucket[b][kind] += 1
    examples.setdefault(b, (gid, mdl[0], kind, len(mr), len(resolved)))

w("=== 分支：点开一条资产后 3D 面板是否出现（按资产组计，共 %d） ===" % TOTAL)
for k, v in bucket.most_common():
    w(f"  {k}")
    w(f"      {v:6d} 组  {v*100.0/TOTAL:5.1f}%   例:{examples[k]}")
w("")
w("=== 各分支的类型构成 ===")
for b in bucket:
    w(f"  {b}\n      " + ", ".join(f"{k}:{v}" for k, v in kinds_of_bucket[b].most_common(6)))
w("")
w(f"=== D 组（面板会出现）：{sum(v for k, v in bucket.items() if k.startswith('D'))} 组，"
  f"首个可定位网格去重 {len(set(first_mesh_by_gid.values()))} 个文件")
w(f"    每组定位到的网格数分布（前 12）：{sorted(resolved_cnt.items())[:12]}")

json.dump({"bucket": dict(bucket), "first_mesh_by_gid": first_mesh_by_gid},
          open(r"D:\TLGL\.scratch\agent_ui_reachable.json", "w", encoding="utf-8"), ensure_ascii=False)
w("")

# ------------------------------------------------- 诚实性核查
w("=== 「客户端未含此文件」是否属实（悬空引用 vs 实体是否存在） ===")
names_in_res = {v[1] for v in res.values() if v[1]}
dangling = [(n, k, th, fh) for fh, n, k, th in
            con.execute("select from_hash, name, kind, to_hash from refs")]
by_kind = Counter()
by_kind_have = Counter()
for n, k, th, fh in dangling:
    if th:
        continue
    by_kind[k] += 1
    if n in names_in_res:
        by_kind_have[k] += 1
w("  kind        悬空引用行数   其中同名实体其实在 resources.name 里")
for k, v in by_kind.most_common():
    w(f"  {k:12s} {v:10d} {by_kind_have[k]:14d}   ({by_kind_have[k]*100.0/v:.1f}%)")
w("")
w("  去重后的名字口径：")
for k in by_kind:
    ds = {n for n, kk, th, fh in dangling if kk == k and not th}
    have = {n for n in ds if n in names_in_res}
    w(f"  {k:12s} 悬空去重名 {len(ds):7d}  其中实体侧存在 {len(have):7d}  ({len(have)*100.0/max(len(ds),1):.1f}%)")
w("")
w("  典型矛盾样本（悬空但实体存在，.mesh/.ske/.mtl/.mdl 各 6 条）：")
seen = set()
for k in (".mesh", ".ske", ".mtl", ".mdl"):
    cnt = 0
    for n, kk, th, fh in dangling:
        if kk != k or th or n not in names_in_res:
            continue
        key = (k, n)
        if key in seen:
            continue
        seen.add(key)
        hits = [h for h, v in res.items() if v[1] == n]
        info = [res[h] for h in hits[:2]]
        w(f"   {k} {n}  引用者={fh}  实体={info}")
        cnt += 1
        if cnt >= 6:
            break
w("")
w("=== dangling 表口径（catalog 自己认定的「只有名字」） ===")
for e, n, have in con.execute(
    "select d.ext, count(*), sum(case when r.name is not null then 1 else 0 end) "
    "from dangling d left join (select distinct name from resources where name is not null) r "
    "on r.name = d.name group by d.ext order by count(*) desc limit 12"):
    w(f"  {str(e):10s} {n:7d} 条，同名实体存在 {have:6d}")
w("")

# path 为空的实体：文件在客户端里，但没归到路径
nop = Counter()
for h, (p, n, e, pak) in res.items():
    if not p:
        nop[e] += 1
w("=== resources 里有 hash 无 path 的实体（=有文件、未归到路径）===")
for e, c in nop.most_common(14):
    w(f"  {str(e):10s} {c:7d}")
w(f"  合计 {sum(nop.values())} / {len(res)} 个去重 hash")
gd = Counter()
mdl_nopath_groups = 0
for gid, r in groups.items():
    if any(res.get(h, ("", "", "", ""))[2] == ".mdl" and not res.get(h, ("", "", "", ""))[0]
           for (_role, h) in members.get(gid, [])):
        gd[r[2]] += 1
        mdl_nopath_groups += 1
w(f"  组内含「有 .mdl 文件但无 path」的组数：{mdl_nopath_groups}  构成 {gd.most_common(6)}")

Path(OUT).write_text("\n".join(out), encoding="utf-8")
print("written", OUT, len(out), "lines")
