"""只读审计 resources.db —— 复算 tlbb-explorer 界面显示的每一个数。
只连只读 URI，不写库，不改任何项目文件。
"""
import re
import sqlite3
import sys
from collections import defaultdict

URI = "file:D:/TLGL/.scratch/resources.db?mode=ro"
TEX_EXT = (".tga", ".dds", ".png", ".jpg", ".jpeg", ".bmp", ".webp")

con = sqlite3.connect(URI, uri=True)
cur = con.cursor()


def q(sql, args=()):
    return list(cur.execute(sql, args))


def one(sql, args=()):
    r = q(sql, args)
    return r[0][0] if r and r[0][0] is not None else 0


def head(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


head("0. 基数")
n_groups = one("SELECT count(*) FROM agroups")
n_res = one("SELECT count(*) FROM resources")
n_refs = one("SELECT count(*) FROM refs")
print("agroups=%d resources=%d refs=%d amembers=%d" % (
    n_groups, n_res, n_refs, one("SELECT count(*) FROM amembers")))
print("distinct pak in resources:", [r[0] for r in q("SELECT DISTINCT pak FROM resources ORDER BY 1")])
print("distinct pak in records:", [r[0] for r in q("SELECT DISTINCT pak FROM records ORDER BY 1")])

# ---------------------------------------------------------------- groups
groups = {}
for gid, hub, hub_path, dirn, stem, kind in q(
        "SELECT id, hub, hub_path, dir, stem, kind FROM agroups"):
    groups[gid] = dict(hub=hub, hub_path=hub_path or "", dir=dirn or "",
                       stem=stem or "", kind=kind or "")

head("1. totalGroups / unnamed / scenarios / kinds")
print("totalGroups =", n_groups, "(stats.json 13080)")


def basename_before_dot(p):
    base = p.rsplit("/", 1)[-1] if p else ""
    return base.split(".", 1)[0] if base else ""


unnamed = [g for g, v in groups.items()
           if not v["stem"] and not basename_before_dot(v["hub_path"])]
print("unnamed (stem 空 且 hub_path 无名) =", len(unnamed), "(stats.json 921)")
unnamed2 = [g for g, v in groups.items() if not v["stem"] and not v["dir"]]
print("另一种口径 stem空且dir空 =", len(unnamed2))
print("stem 空 =", sum(1 for v in groups.values() if not v["stem"]),
      " hub_path 空 =", sum(1 for v in groups.values() if not v["hub_path"]),
      " dir 空 =", sum(1 for v in groups.values() if not v["dir"]))
kindc = defaultdict(int)
for v in groups.values():
    kindc[v["kind"]] += 1
print("kind 分布:", dict(kindc))

# ---------------------------------------------------------------- members
role_kinds = {}
member_n = {}
texture_role_gids = set()
mdl_gids = set()
mesh_member_gids = set()
for gid, rk, mc in q("SELECT gid, count(DISTINCT role), count(*) FROM amembers GROUP BY gid"):
    role_kinds[gid] = rk
    member_n[gid] = mc
for gid, h in q("SELECT gid, hash FROM amembers WHERE role='texture'"):
    texture_role_gids.add(gid)
for gid, h in q("SELECT gid, hash FROM amembers WHERE role='model'"):
    mdl_gids.add(gid)
for gid, h in q("SELECT gid, hash FROM amembers WHERE role='mesh'"):
    mesh_member_gids.add(gid)
print("role=texture 的组:", len(texture_role_gids), " role=model 的组:", len(mdl_gids),
      " role=mesh 的组:", len(mesh_member_gids))
print("hub_path 以 .mdl 结尾的组:", sum(1 for v in groups.values()
                                        if v["hub_path"].lower().endswith(".mdl")))

# ---------------------------------------------------------------- texrefs (texture_refs)
head("2. totalRefs / locatedRefs（texture_refs 口径）")
tex_tot = defaultdict(int)
tex_loc = defaultdict(int)
for gid, name, res in q(
        "SELECT m.gid, r.name, max(CASE WHEN r.to_hash IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM refs r JOIN amembers m ON m.hash=r.from_hash "
        "WHERE r.kind IN ('.tga','.dds','.png','.jpg','.jpeg','.bmp','.webp') "
        "GROUP BY m.gid, r.name"):
    tex_tot[gid] += 1
    tex_loc[gid] += res
sum_tot = sum(tex_tot.values())
sum_loc = sum(tex_loc.values())
print("sum refs_total =", sum_tot, "(stats.json totalRefs 22630)")
print("sum refs_located =", sum_loc, "(stats.json locatedRefs 25)")
print("有贴图引用的组数 =", len(tex_tot), " 有定位成功贴图引用的组数 =",
      sum(1 for g, v in tex_loc.items() if v > 0))
all_edges = one("SELECT count(*) FROM refs WHERE kind IN ('.tga','.dds','.png','.jpg','.jpeg','.bmp','.webp')")
print("贴图类引用边（去重前）=", all_edges, " → 按 (组,名字) 去重后 =", sum_tot)
print("贴图边里 to_hash 非空 =", one(
    "SELECT count(*) FROM refs WHERE kind IN ('.tga','.dds','.png','.jpg','.jpeg','.bmp','.webp') "
    "AND to_hash IS NOT NULL"))
tga_tot = one("SELECT count(*) FROM refs WHERE kind='.tga'")
tga_res = one("SELECT count(*) FROM refs WHERE kind='.tga' AND to_hash IS NOT NULL")
tga_names = one("SELECT count(DISTINCT name) FROM refs WHERE kind='.tga'")
tga_names_res = one("SELECT count(DISTINCT name) FROM refs WHERE kind='.tga' AND to_hash IS NOT NULL")
print(".tga 边 %d/%d = %.3f%% ；.tga 不同名字 %d，其中解析成功 %d = %.2f%%" % (
    tga_res, tga_tot, 100.0 * tga_res / tga_tot, tga_names, tga_names_res,
    100.0 * tga_names_res / tga_names))

# ---------------------------------------------------------------- grades
head("3. grades 复算（假设 hub_decoded 全为真）")
grade = {}
for g, v in groups.items():
    rk = role_kinds.get(g, 0)
    mc = member_n.get(g, 0)
    rt = tex_tot.get(g, 0)
    rl = tex_loc.get(g, 0)
    if mc == 0:
        grade[g] = "D"
    elif rk >= 2 and rt > 0 and rl == rt:
        grade[g] = "A"
    elif rk >= 2:
        grade[g] = "B"
    else:
        grade[g] = "C"
gc = defaultdict(int)
for L in grade.values():
    gc[L] += 1
print("grades:", dict(gc), "(stats.json A20 / B2581 / C10479 / D0)")
no_mem = sum(1 for g in groups if member_n.get(g, 0) == 0)
print("members=0 的组（若主体解码失败才会是 D）:", no_mem)
a_groups = [g for g, L in grade.items() if L == "A"]
print("A 组数:", len(a_groups), "样例 gid:", a_groups[:5])

# ---------------------------------------------------------------- decoded feasibility
head("4. decoded（主体能打开的）可行性")
res_hashes = set(r[0] for r in q("SELECT hash FROM resources"))
bad_hub = [g for g, v in groups.items() if v["hub"] not in res_hashes]
print("hub 不在 resources 里的组:", len(bad_hub), bad_hub[:5])
# hub 有 resources 行，但 pak/offset 对不上 records
n_ok_rec = 0
n_no_rec = 0
no_rec_examples = []
for hub, pak in q("SELECT hash, pak FROM resources WHERE hash IN (SELECT hub FROM agroups)"):
    pass
rows = q("SELECT a.id, a.hub, r.pak, r.offset FROM agroups a JOIN resources r ON r.hash=a.hub")
rec_keys = set((p, h) for p, h in q("SELECT pak, hash FROM records"))
have = set()
miss_rec = []
for gid, hub, pak, off in rows:
    if (pak, hub) in rec_keys:
        have.add(gid)
    else:
        miss_rec.append((gid, hub, pak))
print("hub 能落到 records 索引项的组:", len(have), "；缺 records 项的组:", len(miss_rec), miss_rec[:3])
print("=> 清单侧没有任何一组会 read() 失败" if len(miss_rec) == 0 and len(bad_hub) == 0
      else "=> 清单侧存在无法定位主体的组")

# ---------------------------------------------------------------- preview candidates
head("5. imageCandidates（preview_candidates 口径）")
set1 = set(texture_role_gids)
hub_of = {g: v["hub"] for g, v in groups.items()}
res_by_hash = {r[0]: (r[1], r[2]) for r in
               q("SELECT hash, path, type FROM resources")}
set2 = set()
gid_by_hub = defaultdict(list)
for g, h in hub_of.items():
    gid_by_hub[h].append(g)
# 第二段只看 hub 自己的 refs
for from_hash, name in q("SELECT from_hash, name FROM refs WHERE to_hash IS NOT NULL"):
    if name.lower().endswith(TEX_EXT):
        for g in gid_by_hub.get(from_hash, ()):
            set2.add(g)
print("fallback1 (role=texture 成员) 组数:", len(set1))
print("fallback2 (hub 自己的 refs 且名字像贴图且对上) 组数:", len(set2))
# fallback3: textures_in_dir
tex_dirs = set(r[0] for r in q("SELECT DISTINCT dir FROM resources WHERE type='texture' "
                               "AND dir IS NOT NULL AND trim(dir)<>''"))
set3 = set(g for g, v in groups.items()
           if v["dir"].strip() and v["dir"] in tex_dirs)
print("（若有）fallback3 (同目录里有 texture 资源) 组数:", len(set3))
union = set1 | set2 | set3
print("三级并集 =", len(union), "(stats.json imageCandidates 25)")
print("set1 与 set2 交集:", len(set1 & set2), " set1∪set2 =", len(set1 | set2))
print("dir 非空的组:", sum(1 for v in groups.values() if v["dir"].strip()),
      " 其中该 dir 下能找到 texture 的:", len(set3))
print("resources 里 type=texture 的:", one("SELECT count(*) FROM resources WHERE type='texture'"),
      " 其中 path 非空:", one("SELECT count(*) FROM resources WHERE type='texture' AND path IS NOT NULL AND trim(path)<>''"),
      " 其中 dir 非空:", one("SELECT count(*) FROM resources WHERE type='texture' AND dir IS NOT NULL AND trim(dir)<>''"))
print("webp/png/jpeg 类型的:", q("SELECT type, count(*) FROM resources WHERE type IN ('webp','png','jpeg','texture') GROUP BY type"))

# ---------------------------------------------------------------- 3D 可用性
head("6. 有 .mdl 的组里能真出 3D 的")
mdl_hash = defaultdict(list)
for gid, h in q("SELECT gid, hash FROM amembers WHERE role='model'"):
    mdl_hash[gid].append(h)
rec_hashes = set(h for (h,) in q("SELECT DISTINCT hash FROM records"))


def readable(h):
    return h in rec_hashes and h in res_hashes


mesh_ref_targets = defaultdict(list)
for mh, to in q("SELECT from_hash, to_hash FROM refs WHERE kind='.mesh' AND to_hash IS NOT NULL"):
    mesh_ref_targets[mh].append(to)
mdl_edges = 0
mdl_edges_ok = 0
groups_mesh_located = set()
groups_mesh_readable = set()
for gid, hs in mdl_hash.items():
    got = False
    ok = False
    for h in hs:
        for to in mesh_ref_targets.get(h, []):
            mdl_edges += 1
            if to in res_hashes:
                mdl_edges_ok += 1
                got = True
                if readable(to):
                    ok = True
    if got:
        groups_mesh_located.add(gid)
    if ok:
        groups_mesh_readable.add(gid)
print("有 role=model 成员的组:", len(mdl_hash), "(已知 1685)")
print("这些 mdl 发出的 .mesh 引用边:", mdl_edges, " 其中 to_hash 指向真实 resources:", mdl_edges_ok)
print("→ 至少定位到一个 mesh 的 mdl 组:", len(groups_mesh_located))
print("→ 定位到且 mesh 有 records 索引项（能真读出来）的 mdl 组:", len(groups_mesh_readable))
readable_member_mesh = set()
for gid, h in q("SELECT gid, hash FROM amembers WHERE role='mesh'"):
    if readable(h):
        readable_member_mesh.add(gid)
print("成员里直接带可读 mesh 的组:", len(readable_member_mesh))
three_d = groups_mesh_readable | readable_member_mesh
print("并集（立体预览可用）=", len(three_d), " 占全库 %.1f%%" % (100.0 * len(three_d) / n_groups),
      " 占 mdl 组 %.1f%%" % (100.0 * len(three_d & set(mdl_hash)) / len(mdl_hash)))
mdl_no_mesh = set(mdl_hash) - groups_mesh_located
print("有 mdl 但一个 mesh 都定位不到的组:", len(mdl_no_mesh), sorted(mdl_no_mesh)[:5])
print("mesh 资源总数:", one("SELECT count(*) FROM resources WHERE ext='.mesh' OR type='mesh'"),
      " 有 path 的 mesh:", one("SELECT count(*) FROM resources WHERE (ext='.mesh' OR type='mesh') AND path IS NOT NULL AND trim(path)<>''"))

# ---------------------------------------------------------------- 脏数据
head("7. 脏数据：会影响前端转义/截断")
FIELDS = [
    ("resources", ["path", "dir", "name"]),
    ("agroups", ["stem", "dir", "hub_path"]),
    ("agroup_names", ["name"]),
    ("refs", ["name", "from_path"]),
    ("dangling", ["name"]),
    ("records", ["pak"]),
]
BAD = {
    "angle": re.compile(r"[<>]"),
    "quote": re.compile(r'"'),
    "newline": re.compile(r"[\r\n]"),
    "ctrl": re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"),
    "nonascii": re.compile(r"[^\x20-\x7e]"),
}
for tbl, cols in FIELDS:
    for c in cols:
        try:
            rows = q("SELECT %s FROM %s WHERE %s IS NOT NULL" % (c, tbl, c))
        except sqlite3.Error as e:
            print("skip", tbl, c, e)
            continue
        vals = [r[0] for r in rows]
        stat = {}
        for k, rx in BAD.items():
            hits = [v for v in vals if rx.search(v)]
            stat[k] = hits
        long_ = [v for v in vals if len(v) > 120]
        stat["long>120"] = long_
        empties = sum(1 for v in vals if v.strip() != v)
        line = "%s.%s 共 %d 条：" % (tbl, c, len(vals))
        for k in ("angle", "quote", "newline", "ctrl", "long>120"):
            line += " %s=%d" % (k, len(stat[k]))
        line += " 首尾空白=%d 非ASCII=%d" % (empties, len(stat["nonascii"]))
        mx = max((len(v) for v in vals), default=0)
        line += " 最长=%d" % mx
        print(line)
        for k in ("angle", "quote", "newline", "ctrl", "long>120"):
            for v in stat[k][:2]:
                print("    %s 例: %r" % (k, v[:160]))

# ---------------------------------------------------------------- 引用完整性
head("8. 引用完整性")
print("重复 agroups.id:", one("SELECT count(*) FROM (SELECT id FROM agroups GROUP BY id HAVING count(*)>1)"))
dup_hub = q("SELECT hub, count(*) FROM agroups GROUP BY hub HAVING count(*)>1 LIMIT 5")
print("同一 hub 挂多个组:", one("SELECT count(*) FROM (SELECT hub FROM agroups GROUP BY hub HAVING count(*)>1)"), dup_hub)
print("amembers.gid 不是真组:", one("SELECT count(*) FROM amembers m LEFT JOIN agroups a ON a.id=m.gid WHERE a.id IS NULL"))
print("amembers.hash 不在 resources:", one("SELECT count(*) FROM amembers m LEFT JOIN resources r ON r.hash=m.hash WHERE r.hash IS NULL"))
print("agroup_names.gid 孤儿:", one("SELECT count(*) FROM agroup_names n LEFT JOIN agroups a ON a.id=n.gid WHERE a.id IS NULL"))
print("asset_tags.gid 孤儿:", one("SELECT count(*) FROM asset_tags t LEFT JOIN agroups a ON a.id=t.gid WHERE a.id IS NULL"))
print("asset_fingerprint.gid 孤儿:", one("SELECT count(*) FROM asset_fingerprint f LEFT JOIN agroups a ON a.id=f.gid WHERE a.id IS NULL"))
print("refs.from_hash 不在 resources:", one("SELECT count(*) FROM refs r LEFT JOIN resources x ON x.hash=r.from_hash WHERE x.hash IS NULL"))
print("refs.to_hash 非空但不在 resources:", one(
    "SELECT count(*) FROM refs r LEFT JOIN resources x ON x.hash=r.to_hash WHERE r.to_hash IS NOT NULL AND x.hash IS NULL"))
print("relations.from_hash 不在 resources:", one("SELECT count(*) FROM relations e LEFT JOIN resources x ON x.hash=e.from_hash WHERE x.hash IS NULL"))
print("relations.to_hash 不在 resources:", one("SELECT count(*) FROM relations e LEFT JOIN resources x ON x.hash=e.to_hash WHERE x.hash IS NULL"))
print("resources.hash 无 records 索引项:", one(
    "SELECT count(*) FROM resources r LEFT JOIN records c ON c.hash=r.hash AND c.pak=r.pak WHERE c.hash IS NULL"))
print("records.hash 不在 resources:", one("SELECT count(*) FROM records c LEFT JOIN resources r ON r.hash=c.hash WHERE r.hash IS NULL"))
print("assets.primary_hash 不在 resources:", one("SELECT count(*) FROM assets a LEFT JOIN resources r ON r.hash=a.primary_hash WHERE r.hash IS NULL"))
print("assets.grp 不是真组:", one("SELECT count(*) FROM assets a LEFT JOIN agroups g ON g.id=a.grp WHERE g.id IS NULL"))
print("blobs.hash 不在 resources:", one("SELECT count(*) FROM blobs b LEFT JOIN resources r ON r.hash=b.hash WHERE r.hash IS NULL"))
print("dangling 名字数:", one("SELECT count(*) FROM dangling"),
      " refs 里 to_hash 为空的边:", one("SELECT count(*) FROM refs WHERE to_hash IS NULL"),
      " refs 里 to_hash 空的不同名字:", one("SELECT count(DISTINCT name) FROM refs WHERE to_hash IS NULL"))
# hash 格式脏
print("hub 不是 16 位十六进制的组:", q("SELECT count(*) FROM agroups WHERE hub NOT GLOB '[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]'"))
print("resources.hash 非法/短:", q("SELECT count(*) FROM resources WHERE length(hash)<>16"))
print("amembers.hash 非法:", q("SELECT count(*) FROM amembers WHERE length(hash)<>16"))
print("refs.name 里带路径分隔的:", one("SELECT count(*) FROM refs WHERE name LIKE '%/%'"),
      " refs.kind 为空的:", one("SELECT count(*) FROM refs WHERE kind IS NULL OR kind=''"))
print("resources.path 与 self_path 不一致:", one("SELECT count(*) FROM resources WHERE self_path IS NOT NULL AND path IS NOT NULL AND self_path<>path"))
print("resources 无 path 的:", one("SELECT count(*) FROM resources WHERE path IS NULL OR trim(path)=''"))
print("meta asset:groups vs agroups:", one("SELECT value FROM meta WHERE key='asset:groups'"))
con.close()
