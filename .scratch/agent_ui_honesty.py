import sqlite3
from collections import Counter
from pathlib import Path
con = sqlite3.connect(r"file:D:/TLGL/.scratch/resources.db?mode=ro", uri=True)
L = []
def w(s=""): L.append(str(s))

w("=== 争议实体 00a9fbe2315293e7 ===")
for r in con.execute("select hash,name,ext,path,dir,type,subtype,pak,offset,original,stored,named,codec from resources where hash='00a9fbe2315293e7'"):
    w("  resources: " + repr(tuple(r)))
for r in con.execute("select pak,gen,hash,offset,stored,original,method,ver from records where hash='00a9fbe2315293e7'"):
    w("  records  : " + repr(tuple(r)))
for r in con.execute("select sha,size from blobs where hash='00a9fbe2315293e7'"):
    w("  blobs    : " + repr(tuple(r)))
w("  它自己发出的引用：")
for r in con.execute("select name,kind,to_hash from refs where from_hash='00a9fbe2315293e7'"):
    w("    " + repr(tuple(r)))
w("  它属于哪些组 / 角色：")
for r in con.execute("select gid,role from amembers where hash='00a9fbe2315293e7'"):
    w("    " + repr(tuple(r)))
w("  同目录同族 b0 主体的资源行（对照）：")
for r in con.execute("select hash,name,path,type,original from resources where name like 'w1351_pets_jiuxiaozhanlong_b0%' limit 6"):
    w("    " + repr(tuple(r)))
w("  有没有任何 resources.name 含 jiuxiaozhanlong_b8 且 ext in (.mesh,.ske,.mtl,.mdl)：")
c = con.execute("select count(*) from resources where name like '%jiuxiaozhanlong_b8%'").fetchone()[0]
w(f"    {c} 条")
w("  tree 侧（实体文件目录）是否存在 *jiuxiaozhanlong_b8*.mesh/.ske/.mtl/.mdl：见 find 结果（外部核对，0 条）")
w("")

w("=== 「附属文件 N 个：客户端未含这些文件」这句话的影响面 ===")
# inspector.rs:527-539 —— members 里 path 为 None 的就写「客户端未含这些文件」
q = ("select count(distinct m.gid) from amembers m join resources r on r.hash=m.hash "
     "where r.path is null or r.path=''")
w(f"  至少含一个「有 hash 无 path」成员的组数：{con.execute(q).fetchone()[0]} / 13080")
q2 = ("select r.type, count(*) from amembers m join resources r on r.hash=m.hash "
      "where r.path is null or r.path='' group by r.type order by count(*) limit 12")
for r in con.execute(q2):
    w(f"    type={r[0]!r} {r[1]}")
# 这些实体到底在不在客户端：records 里有容器+偏移+大小即为「在」
q3 = ("select count(*) from amembers m join resources r on r.hash=m.hash "
      "left join records k on k.hash=m.hash where (r.path is null or r.path='') and k.hash is not null")
q4 = ("select count(*) from amembers m join resources r on r.hash=m.hash "
      "left join records k on k.hash=m.hash where (r.path is null or r.path='') and k.hash is null")
w(f"  其中在 records 里有容器/偏移/大小（=字节确实在客户端里）：{con.execute(q3).fetchone()[0]} 条成员")
w(f"  其中 records 里也没有的：{con.execute(q4).fetchone()[0]} 条成员")
q5 = ("select count(*) from amembers m join resources r on r.hash=m.hash "
      "where (r.path is null or r.path='') and r.name is not null and r.name<>''")
w(f"  成员里有 hash 无 path 但有 name 的：{con.execute(q5).fetchone()[0]} 条")
Path(r"D:\TLGL\.scratch\agent_ui_honesty.txt").write_text("\n".join(L), encoding="utf-8")
print("ok")
