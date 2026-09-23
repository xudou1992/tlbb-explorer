# -*- coding: utf-8 -*-
"""只读审计（第二轮：细节与脏数据样本）"""
import re, sqlite3
from collections import defaultdict
con = sqlite3.connect("file:D:/TLGL/.scratch/resources.db?mode=ro", uri=True)
cur = con.cursor()
def q(s, a=()): return list(cur.execute(s, a))
def one(s, a=()):
    r = q(s, a); return r[0][0] if r and r[0][0] is not None else 0
def p(*a): print(*a, flush=True)

p("\n--- assets 表语义 ---")
p("assets 行数:", one("SELECT count(*) FROM assets"))
p("assets 里 distinct grp:", one("SELECT count(DISTINCT grp) FROM assets"))
p("grp 样本:", [r[0] for r in q("SELECT DISTINCT grp FROM assets LIMIT 6")])
p("grp 是数字吗:", q("SELECT count(*) FROM assets WHERE grp GLOB '[0-9]*'"))
p("assets.kind 分布:", q("SELECT kind,count(*) FROM assets GROUP BY kind ORDER BY 2 DESC LIMIT 8"))
p("assets.grp 能对上 agroups.id 的行数:", one("SELECT count(*) FROM assets a JOIN agroups g ON g.id=a.grp"))
p("primary_hash 作为 hub 的组数:", one("SELECT count(*) FROM agroups g JOIN assets a ON a.primary_hash=g.hub"))

p("\n--- blobs 里那个孤儿 ---")
p(q("SELECT b.hash, b.size FROM blobs b LEFT JOIN resources r ON r.hash=b.hash WHERE r.hash IS NULL"))
p("blobs 行数:", one("SELECT count(*) FROM blobs"), " resources 行数:", one("SELECT count(*) FROM resources"))

p("\n--- dangling 与未解析 refs 的差 ---")
p("dangling 名字数:", one("SELECT count(*) FROM dangling"))
p("refs 未解析不同名字数:", one("SELECT count(DISTINCT name) FROM refs WHERE to_hash IS NULL"))
p("未解析但不在 dangling 的名字:", q(
  "SELECT DISTINCT name FROM refs WHERE to_hash IS NULL AND name NOT IN (SELECT name FROM dangling) LIMIT 6"))
p("其边数:", one("SELECT count(*) FROM refs WHERE to_hash IS NULL AND name NOT IN (SELECT name FROM dangling)"))
p("dangling 里但 refs 中不存在该未解析名的:", q(
  "SELECT name FROM dangling WHERE name NOT IN (SELECT DISTINCT name FROM refs WHERE to_hash IS NULL) LIMIT 6"))

p("\n--- 非 ASCII 名字样本 ---")
NA = re.compile(r"[^\x20-\x7e]")
for sql, lbl in [("SELECT DISTINCT name FROM refs", "refs.name"),
                 ("SELECT name FROM agroup_names", "agroup_names.name"),
                 ("SELECT name FROM dangling", "dangling.name")]:
    hits = [r[0] for r in q(sql) if NA.search(r[0])]
    p("%s 非ASCII 条数(去重后)=%d" % (lbl, len(hits)))
    for v in hits[:3]:
        p("   ", repr(v))

p("\n--- path vs self_path ---")
p("不同的行数:", one("SELECT count(*) FROM resources WHERE self_path IS NOT NULL AND path IS NOT NULL AND self_path<>path"))
for r in q("SELECT path, self_path FROM resources WHERE self_path<>path LIMIT 3"):
    p("   path=%r self=%r" % (r[0], r[1]))
p("self_path 为空的:", one("SELECT count(*) FROM resources WHERE self_path IS NULL OR trim(self_path)=''"))
p("path 为空:", one("SELECT count(*) FROM resources WHERE path IS NULL OR trim(path)=''"),
  "  占 %.0f%%" % (100.0*one("SELECT count(*) FROM resources WHERE path IS NULL OR trim(path)=''")/one("SELECT count(*) FROM resources")))
p("path 为空的资源 type 分布:", q("SELECT type,count(*) FROM resources WHERE path IS NULL OR trim(path)='' GROUP BY type ORDER BY 2 DESC LIMIT 6"))
p("texture 资源:", one("SELECT count(*) FROM resources WHERE type='texture'"),
  " 其中有 path:", one("SELECT count(*) FROM resources WHERE type='texture' AND path IS NOT NULL AND trim(path)<>''"))
p("texture 有 path 且被登记为某组成员的:", one(
  "SELECT count(*) FROM amembers m JOIN resources r ON r.hash=m.hash WHERE r.type='texture' AND r.path IS NOT NULL AND trim(r.path)<>''"))
p("被登记为成员(any role)的 distinct hash:", one("SELECT count(DISTINCT hash) FROM amembers"))

p("\n--- 3D 细节 ---")
res = set(r[0] for r in q("SELECT hash FROM resources"))
mdl = defaultdict(list)
for gid, h in q("SELECT gid, hash FROM amembers WHERE role='model'"):
    mdl[gid].append(h)
edges = defaultdict(list)
for f, t in q("SELECT from_hash, to_hash FROM refs WHERE kind='.mesh'"):
    edges[f].append(t)
full, partial, none_ = 0, 0, 0
per_group_edges = []
for gid, hs in mdl.items():
    es = [t for h in hs for t in edges.get(h, [])]
    if not es:
        none_ += 1; continue
    ok = sum(1 for t in set(es) if t in res)
    per_group_edges.append((len(set(es)), ok))
    if ok == len(set(es)): full += 1
    else: partial += 1
p("有 model 成员的组:", len(mdl))
p("  引用了 mesh 且全部能定位:", full)
p("  只定位到一部分:", partial)
p("  一条 mesh 引用都没有:", none_)
p("  至少一个 mesh 能定位:", full + partial)
p("mesh 成员里 path 为空的成员数:", one(
  "SELECT count(*) FROM amembers m WHERE m.role='mesh' AND NOT EXISTS (SELECT 1 FROM resources r WHERE r.hash=m.hash AND trim(r.path)<>'')"))
p("hub 本身就是 texture 的组:", one(
  "SELECT count(*) FROM agroups g JOIN resources r ON r.hash=g.hub WHERE r.type='texture'"))
p("hub 的 type 分布:", q("SELECT r.type,count(*) FROM agroups g JOIN resources r ON r.hash=g.hub GROUP BY r.type ORDER BY 2 DESC LIMIT 8"))
p("hub 的 ext 分布:", q("SELECT r.ext,count(*) FROM agroups g JOIN resources r ON r.hash=g.hub GROUP BY r.ext ORDER BY 2 DESC LIMIT 8"))

p("\n--- 解码可行性再核 ---")
p("records 覆盖 resources:", one("SELECT count(*) FROM resources r JOIN records c ON c.hash=r.hash AND c.pak=r.pak"))
p("records 里 offset/stored 为 0 的资源:", one("SELECT count(*) FROM resources WHERE stored=0 OR original=0"))
p("meta type:missing 对应资源:", one("SELECT count(*) FROM resources WHERE type='missing'"))
p("original<0 或异常:", q("SELECT count(*) FROM resources WHERE original<0"))
p("resources 里 named=1 的:", one("SELECT count(*) FROM resources WHERE named=1"))

p("\n--- 长度分布（截断策略） ---")
for sql, lbl in [("SELECT path FROM resources", "resources.path"),
                 ("SELECT stem FROM agroups", "agroups.stem"),
                 ("SELECT dir FROM agroups", "agroups.dir"),
                 ("SELECT hub_path FROM agroups", "agroups.hub_path"),
                 ("SELECT name FROM agroup_names", "agroup_names.name"),
                 ("SELECT name FROM refs", "refs.name")]:
    L = [len(r[0]) for r in q(sql) if r[0]]
    L.sort()
    p("%-20s n=%d p50=%d p95=%d p99=%d max=%d >60=%d >90=%d >120=%d" % (
        lbl, len(L), L[int(len(L)*.5)], L[int(len(L)*.95)], L[int(len(L)*.99)], L[-1],
        sum(1 for x in L if x > 60), sum(1 for x in L if x > 90), sum(1 for x in L if x > 120)))
p(">120 的 resources.path 样本:")
for r in q("SELECT path FROM resources WHERE length(path)>120 LIMIT 3"): p("   ", r[0])
p("最长 refs.name:", q("SELECT name FROM refs ORDER BY length(name) DESC LIMIT 2"))
con.close()
