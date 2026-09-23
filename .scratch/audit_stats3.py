# -*- coding: utf-8 -*-
"""只读审计第三轮：把 25 这个数钉死 + mdl 精确口径 + 剩余完整性"""
import re, sqlite3
from collections import defaultdict
con = sqlite3.connect("file:D:/TLGL/.scratch/resources.db?mode=ro", uri=True)
cur = con.cursor()
def q(s, a=()): return list(cur.execute(s, a))
def one(s, a=()):
    r = q(s, a); return r[0][0] if r and r[0][0] is not None else 0
def p(*a): print(*a, flush=True)

# 25 个 role=texture 成员
tex_mem = {g: h for g, h in q("SELECT gid, hash FROM amembers WHERE role='texture'")}
p("role=texture 成员:", len(tex_mem))
# 25 条解析成功的贴图引用边
edges = q("SELECT m.gid, r.name, r.to_hash, r.from_hash, r.kind FROM refs r "
          "JOIN amembers m ON m.hash=r.from_hash "
          "WHERE r.kind IN ('.tga','.dds','.png','.jpg','.jpeg','.bmp','.webp') AND r.to_hash IS NOT NULL")
p("解析成功的贴图引用边:", len(edges), "涉及组:", len(set(e[0] for e in edges)))
gids_edge = set(e[0] for e in edges)
p("这批 gid 与 role=texture 的 gid 集合是否相同:", gids_edge == set(tex_mem))
p("to_hash 是否都等于该组的 texture 成员:",
  sum(1 for g, n, t, f, k in edges if tex_mem.get(g) == t), "/", len(edges))
p("这 25 条边的 from 文件 kind:", q("SELECT kind, count(*) FROM refs WHERE to_hash IN (SELECT hash FROM amembers WHERE role='texture') GROUP BY kind"))

# 有贴图名字线索的组
p("\n有 ≥1 条贴图名字引用的组:", one(
  "SELECT count(DISTINCT m.gid) FROM refs r JOIN amembers m ON m.hash=r.from_hash "
  "WHERE r.kind IN ('.tga','.dds','.png','.jpg','.jpeg','.bmp','.webp')"))
p("有 ≥1 条 .mtl 引用的组:", one(
  "SELECT count(DISTINCT m.gid) FROM refs r JOIN amembers m ON m.hash=r.from_hash WHERE r.kind='.mtl'"))
p("成员里出现过的 role:", q("SELECT role,count(DISTINCT gid) FROM amembers GROUP BY role ORDER BY 2 DESC"))

# mdl 精确口径
res = set(r[0] for r in q("SELECT hash FROM resources"))
mdl = defaultdict(list)
for gid, h in q("SELECT gid, hash FROM amembers WHERE role='model'"):
    mdl[gid].append(h)
mesh_edges = defaultdict(set)
for f, t in q("SELECT from_hash, to_hash FROM refs WHERE kind='.mesh' AND to_hash IS NOT NULL"):
    mesh_edges[f].add(t)
all_edges = defaultdict(set)
for f, t in q("SELECT from_hash, to_hash FROM refs WHERE kind='.mesh'"):
    all_edges[f].add(f if False else (t or 'NULL'))
ge1 = all_ok = partial = zero_located = no_edge = 0
for gid, hs in mdl.items():
    total = set()
    located = set()
    for h in hs:
        for (to,) in q("SELECT COALESCE(to_hash,'NULL') FROM refs WHERE from_hash=?1 AND kind='.mesh'", (h,)):
            if to != 'NULL':
                total.add(to)
                if to in res:
                    located.add(to)
    if not total:
        no_edge += 1
    elif not located:
        zero_located += 1
    elif located == total:
        all_ok += 1; ge1 += 1
    else:
        partial += 1; ge1 += 1
p("\n1685 个 mdl 组：全部 mesh 引用都能定位 = %d；只能定位一部分 = %d；一条都定位不到但有引用 = %d；完全没有 mesh 引用 = %d"
  % (all_ok, partial, zero_located, no_edge))
p("至少一个 mesh 能定位（= 能出 3D）:", all_ok + partial, "占 mdl 组 %.1f%%" % (100.0*(all_ok+partial)/len(mdl)),
  "占全库 %.1f%%" % (100.0*(all_ok+partial)/one("SELECT count(*) FROM agroups")))

# 完整性剩余
p("\nblobs 里非 16 位十六进制的 hash:", one("SELECT count(*) FROM blobs WHERE hash NOT GLOB '[0-9a-f]*' OR length(hash)<>16"))
p("blobs 非十六进制样本:", q("SELECT hash, size FROM blobs WHERE length(hash)<>16 LIMIT 3"))
p("resources 有但 blobs 没有:", one("SELECT count(*) FROM resources r LEFT JOIN blobs b ON b.hash=r.hash WHERE b.hash IS NULL"))
p("records 行数:", one("SELECT count(*) FROM records"), "meta records:", one("SELECT value FROM meta WHERE key='records'"))
p("amembers 里 (gid,hash) 重复:", one("SELECT count(*) FROM (SELECT gid,hash FROM amembers GROUP BY gid,hash HAVING count(*)>1)"))
p("同一 hash 挂在多个组:", one("SELECT count(*) FROM (SELECT hash FROM amembers GROUP BY hash HAVING count(*)>1)"),
  "成员总数:", one("SELECT count(*) FROM amembers"))
p("agroup_names 同名挂多组:", one("SELECT count(*) FROM (SELECT name FROM agroup_names GROUP BY name HAVING count(*)>1)"))
p("refs.name 含空格:", one("SELECT count(*) FROM refs WHERE name LIKE '% %'"),
  "  含 #:", one("SELECT count(*) FROM refs WHERE name LIKE '%#%'"),
  "  含反斜杠:", one("SELECT count(*) FROM refs WHERE name LIKE '%\\\\%'"),
  "  含中文:", one("SELECT count(*) FROM refs WHERE name GLOB '*[^ -~]*'"))
p("agroup_names 含中文:", one("SELECT count(*) FROM agroup_names WHERE name GLOB '*[^ -~]*'"))
p("stem 含中文/非ASCII 的组:", one("SELECT count(*) FROM agroups WHERE stem GLOB '*[^ -~]*'"),
  " dir 含非ASCII:", one("SELECT count(*) FROM agroups WHERE dir GLOB '*[^ -~]*'"))
p("stem 含空格的组:", one("SELECT count(*) FROM agroups WHERE stem LIKE '% %'"))
p("stem 等于 hub 十六进制的组（无名字回退）:", one("SELECT count(*) FROM agroups WHERE stem='' "))
p("hub_path 不以 . 结尾扩展名的组:", one("SELECT count(*) FROM agroups WHERE hub_path NOT LIKE '%.%' AND hub_path<>''"))
p("resources.name 含路径分隔:", one("SELECT count(*) FROM resources WHERE name LIKE '%/%'"))
p("ext 为空的资源:", one("SELECT count(*) FROM resources WHERE ext IS NULL OR ext=''"))
p("width/height 为 0 的 texture:", one("SELECT count(*) FROM resources WHERE type='texture' AND (width=0 OR height=0)"))
con.close()
