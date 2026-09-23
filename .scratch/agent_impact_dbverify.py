"""agent_impact_dbverify.py — 用项目自己的 catalog.refs 表独立核对 .mdl→.mesh 定位结果。

只读 resources.db；对照 agent_impact_result.json 里我方的 bodies/resolved 计数。
若两边不一致就逐条列出，用来抓我方定位器的错。
"""
import io
import json
import os
import sqlite3
from collections import Counter

HERE = r"D:\TLGL\.scratch"
DB = os.path.join(HERE, "resources.db")
RES = os.path.join(HERE, "agent_impact_result.json")
OUT = os.path.join(HERE, "agent_impact_dbverify.txt")

d = json.load(io.open(RES, encoding="utf-8"))
rows = {r["mdl"].lower(): r for r in d["mdl_rows"]}

con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
mine_slots = sum(r["bodies"] for r in rows.values())
mine_missing = sum(r["bodies"] - r["resolved"] for r in rows.values())
db_tot = db_unres = db_with = 0
db_keys = set()
diffs = []
db_all_unres = 0
per = {}
for fpath, name, to_hash in con.execute(
        "SELECT from_path, name, to_hash FROM refs WHERE kind='.mesh' AND from_path LIKE '%.mdl'"):
    per.setdefault(fpath, []).append((name, to_hash))
for path, rs in per.items():
    key = path.lower().lstrip("./\\").strip()
    key = "/".join([p for p in key.split("/") if p])
    db_keys.add(key)
    tot = len(rs)
    unres = sum(1 for _n, h in rs if h is None or h == "")
    db_tot += tot
    db_unres += unres
    db_with += 1
    if unres == tot:
        db_all_unres += 1
    mine = rows.get(key)
    if mine is None:
        diffs.append("只在 DB: %s (tot=%d unres=%d)" % (path, tot, unres))
        continue
    if mine["bodies"] != tot or (mine["bodies"] - mine["resolved"]) != unres:
        diffs.append("计数不一致 %s mine bodies=%d resolved=%d | db tot=%d unres=%d" % (
            path, mine["bodies"], mine["resolved"], tot, unres))

only_mine = [r["mdl"] for k, r in rows.items() if r["bodies"] > 0 and k not in db_keys]

fh = io.open(OUT, "w", encoding="utf-8")
fh.write("独立核对：catalog.refs(.mdl→.mesh)  vs  agent_impact_census 的定位结果\n\n")
fh.write("%-34s %10s %10s\n" % ("口径", "我方(tree)", "DB(refs表)"))
fh.write("%-34s %10d %10d\n" % (".mdl→.mesh 槽位总数", mine_slots, db_tot))
fh.write("%-34s %10d %10d\n" % ("其中引用名对不到实体", mine_missing, db_unres))
fh.write("%-34s %10d %10d\n" % ("带 >=1 个网格引用的 .mdl", sum(1 for r in rows.values() if r["bodies"] > 0), db_with))
fh.write("%-34s %10d %10d\n" % ("全部引用都落空的 .mdl", sum(1 for r in rows.values() if r["bodies"] > 0 and r["resolved"] == 0), db_all_unres))
fh.write("\n逐条差异 %d 处：\n" % len(diffs))
for x in diffs[:40]:
    fh.write("  " + x + "\n")
fh.write("\n只在我方出现、DB 里没有该 .mdl 的引用记录: %d\n" % len(only_mine))
for x in only_mine[:20]:
    fh.write("  " + x + "\n")
fh.close()
print("written")
