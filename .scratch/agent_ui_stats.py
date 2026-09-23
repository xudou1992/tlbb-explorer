"""只读统计：13,080 个资产组里，每一种「3D 面板看不到 / 画不出」的分支各占多少。

不改任何源码、不写库：sqlite 以 mode=ro 打开。
输出：D:\TLGL\.scratch\agent_ui_stats.txt (UTF-8)
"""
import json
import sqlite3
from collections import Counter
from pathlib import Path

DB = r"file:D:/TLGL/.scratch/resources.db?mode=ro"
OUT = Path(r"D:\TLGL\.scratch\agent_ui_stats.txt")

con = sqlite3.connect(DB, uri=True)
con.row_factory = sqlite3.Row
out = []


def w(s=""):
    out.append(s)


TOTAL = con.execute("select count(*) c from agroups").fetchone()["c"]
w(f"总资产组 agroups = {TOTAL}")
w(f"amembers = {con.execute('select count(*) c from amembers').fetchone()['c']}")
res_rows = con.execute("select count(*) c, count(distinct hash) d from resources").fetchone()
w(f"resources 行 = {res_rows['c']} / distinct hash = {res_rows['d']}")
w("")

# 每组：有没有「带 path 且 path 以 .mdl 结尾」的成员（=inspector.rs 能否拿到 mdl_member）
# 复刻 inspector.rs:423-435 + sqlite.rs:321-323 的 ORDER BY m.role, r.path
q_mdl = """
SELECT m.hash AS hash, r.path AS path
FROM amembers m JOIN resources r ON r.hash = m.hash
WHERE m.gid = :g AND lower(r.path) LIKE '%.mdl'
ORDER BY m.role, r.path LIMIT 1
"""
groups = con.execute("select id, stem, kind, n, n_mesh, n_mtl, n_ske, n_ani, n_tex from agroups").fetchall()

# 组内是否含 .mdl 成员但 path 为空（=有文件但没归到路径上）
q_mdl_nopath = """
SELECT count(*) c FROM amembers m JOIN resources r ON r.hash = m.hash
WHERE m.gid = :g AND lower(r.name) LIKE '%.mdl' AND (r.path is null or r.path = '')
"""
q_any_mdl_name = """
SELECT count(*) c FROM amembers m JOIN resources r ON r.hash = m.hash
WHERE m.gid = :g AND lower(r.name) LIKE '%.mdl'
"""

# 该 mdl 的网格引用（refs 由 catalog 从 .mdl 串表里解出来，与 resolve_name 同一套名字）
q_mesh_refs = "select name, to_hash th, ambig from refs where from_hash = :h and kind = '.mesh'"
q_ske_refs = "select name, to_hash th from refs where from_hash = :h and kind = '.ske'"

bucket = Counter()
reachable_files = {}      # 组 -> 第一个可解析网格名（近似：第一个 to 非空的 mesh 引用）
all_reachable_names = set()
first_body_fail = Counter()
mdl_hit_bodies = Counter()
examples = {}
kinds_of_bucket = Counter()

for g in groups:
    gid = g["id"]
    m = con.execute(q_mdl, {"g": gid}).fetchone()
    if m is None:
        # 为什么没有：组里根本没有 .mdl 名字的成员，还是成员没路径？
        any_name = con.execute(q_any_mdl_name, {"g": gid}).fetchone()["c"]
        no_path = con.execute(q_mdl_nopath, {"g": gid}).fetchone()["c"]
        if no_path:
            b = "A2 mdl 成员存在但 path 为空（有文件没归到组路径）"
        elif any_name:
            b = "A3 组内有 .mdl 名字但成员不在 amembers"
        elif g["n_mesh"] or g["n_ske"] or g["n_mtl"]:
            b = "A1b 组里记着网格/骨骼/材质计数，却没有 .mdl 主体"
        else:
            b = "A1a 组里压根没有模型类文件（贴图/特效/其它）"
        bucket[b] += 1
        kinds_of_bucket[(b, g["kind"])] += 1
        examples.setdefault(b, (gid, g["stem"], g["kind"], g["n"], g["n_mesh"]))
        continue

    mr = con.execute(q_mesh_refs, {"h": m["hash"]}).fetchall()
    sk = con.execute(q_ske_refs, {"h": m["hash"]}).fetchall()
    resolved = [r for r in mr if r["th"]]
    if not mr and not any(r["th"] for r in sk):
        b = "B mdl 解析不出任何组成（refs 里没有 .mesh/.ske）"
    elif not mr:
        b = "B2 mdl 只带骨骼引用（组成树只有「骨骼 …」那一行）"
    elif not resolved:
        b = "C mdl 有网格引用但一个都没定位到实体（mesh.hash 缺失）"
    else:
        b = "D 面板会出现（至少 1 个网格定位到）"
        first = resolved[0]["name"]
        reachable_files[gid] = first
        all_reachable_names.add(first)
        mdl_hit_bodies[len(resolved)] += 1
    bucket[b] += 1
    kinds_of_bucket[(b, g["kind"])] += 1
    examples.setdefault(b, (gid, m["path"], g["kind"], len(mr), len(resolved)))

w("=== 分支 1：从「点开一条资产」到 3D 面板是否出现（按组计，13,080） ===")
for k, v in bucket.most_common():
    w(f"  {k:62s} {v:6d}  {v*100.0/TOTAL:5.1f}%   例:{examples[k]}")
w("")

w("=== 各分支的类型构成（前 6） ===")
byb = {}
for (b, kind), v in kinds_of_bucket.items():
    byb.setdefault(b, []).append((v, kind))
for b in bucket:
    top = ", ".join(f"{k}:{v}" for v, k in sorted(byb[b], reverse=True)[:6])
    w(f"  {b}\n      {top}")
w("")

w(f"=== 走到面板（D）的组：{len(reachable_files)}，其首个可定位网格去重后 {len(all_reachable_names)} 个文件")
w(f"    每组定位到的网格数分布：{sorted(mdl_hit_bodies.items())[:12]}")

json.dump(
    {"bucket": dict(bucket), "first_mesh_by_gid": {str(k): v for k, v in reachable_files.items()}},
    open(r"D:\TLGL\.scratch\agent_ui_reachable.json", "w", encoding="utf-8"),
    ensure_ascii=False,
)
w("")

# ------------------------------------------------ 诚实性核查
w("=== 「客户端未含此文件」是否属实：悬空引用 vs 实体存在性 ===")
# refs.to_hash IS NULL = 后端会说「客户端未含此文件」；但同名实体是否其实就在 resources 里？
rows = con.execute(
    "select r.kind k, count(*) n, "
    " sum(case when e.h is not null then 1 else 0 end) exists_same_name "
    "from refs r left join (select distinct name h from resources where name is not null) e "
    "on e.h = r.name where r.to_hash is null group by r.kind order by n desc"
).fetchall()
w("  kind            悬空引用数   其中同名实体其实在 resources.name 里")
for r in rows:
    w(f"  {r['k']:14s} {r['n']:10d} {r['exists_same_name']:14d}")
w("")

dup = con.execute(
    "select r.name n, count(distinct r.from_hash) src, r.kind k from refs r "
    "left join resources e on e.name = r.name "
    "where r.to_hash is null and e.name is not null group by r.name order by src desc limit 15"
).fetchall()
w("  同名的悬空引用（其实 resources.name 有值）Top15：")
for d in dup:
    real = con.execute(
        "select hash, path, pak, original from resources where name = ? limit 3", (d["n"],)
    ).fetchall()
    w(f"   {d['n']} 被 {d['src']} 个来源引用，未定位；实体侧：{[tuple(x) for x in real]}")
w("")

# 只有「名字」的悬空（resources 里确实没有）里，抽 .mesh 与 .ske 各看是否存在于 tree
w("=== 悬空 .mesh / .ske 名单里，有多少名字能在实体清单 resources.name 找到（=谎报） ===")
for kind in (".mesh", ".ske", ".mtl", ".mdl"):
    tot = con.execute("select count(distinct name) c from refs where to_hash is null and kind=?", (kind,)).fetchone()["c"]
    have = con.execute(
        "select count(distinct r.name) c from refs r join resources e on e.name = r.name "
        "where r.to_hash is null and r.kind = ?", (kind,)
    ).fetchone()["c"]
    w(f"  {kind}: 悬空去重名 {tot}，其中 resources.name 里其实有 {have} 个（{have*100.0/max(tot,1):.1f}%）")
w("")
w("=== dangling 表视角（catalog 自己认定的「只有名字」清单） ===")
d2 = con.execute(
    "select d.ext e, count(*) n, sum(case when r.name is not null then 1 else 0 end) exists "
    "from dangling d left join resources r on r.name = d.name group by d.ext order by n desc limit 12"
).fetchall()
for r in d2:
    w(f"  {r['e']:8s} {r['n']:7d} 条，其中同名实体存在 {r['exists']:6d}")
w("")

# 有实体但 path 为空的（=文件在客户端里，但没归到路径 → inspector 认为组里没有 .mdl）
nop = con.execute(
    "select ext, count(*) c from resources where (path is null or path='') group by ext order by c desc limit 12"
).fetchall()
w("=== resources 里 path 为空的实体（有 hash 无路径）===")
for r in nop:
    w(f"  {r['ext']:8s} {r['c']:7d}")
tot_np = con.execute("select count(*) c from resources where path is null or path=''").fetchone()["c"]
w(f"  合计 {tot_np}")
w("")

groups_nopath = con.execute(
    "select count(distinct m.gid) c from amembers m join resources r on r.hash=m.hash "
    "where (r.path is null or r.path='') and lower(r.name) like '%.mdl'"
).fetchone()["c"]
w(f"组内含「有 hash 无 path」的 .mdl 成员的组数：{groups_nopath}")

Path(OUT).write_text("\n".join(out), encoding="utf-8")
print("written", OUT)
