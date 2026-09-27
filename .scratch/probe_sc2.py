import os, sqlite3, traceback, json

OUT = r"D:\TLGL\.scratch\probe_sc2.txt"
lines = []
def p(*a): lines.append(" ".join(str(x) for x in a))

db = r"D:\TLGL\.scratch\resources.db"
try:
    con = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)
    cur = con.cursor()

    # 找 dir 为空但 type=scene 的行：看 src / self_path / name
    p("=== type=scene AND dir='' sample ===")
    cur.execute("SELECT hash,name,ext,type,subtype,stored,original,pak,gen,offset,named,props,src,self_path FROM resources WHERE type='scene' AND dir='' LIMIT 12")
    cols=[d[0] for d in cur.description]
    p("  cols: "+",".join(cols))
    for r in cur.fetchall(): p("  " + repr(r))

    p("=== type=scene AND dir='' src distribution ===")
    cur.execute("SELECT src, COUNT(*) FROM resources WHERE type='scene' AND dir='' GROUP BY src")
    for r in cur.fetchall(): p("  src=%r n=%d" % r)

    p("=== type=scene src distribution (all) ===")
    cur.execute("SELECT src, COUNT(*) FROM resources WHERE type='scene' GROUP BY src")
    for r in cur.fetchall(): p("  src=%r n=%d" % r)

    p("=== type=scene named distribution ===")
    cur.execute("SELECT named, COUNT(*) FROM resources WHERE type='scene' GROUP BY named")
    for r in cur.fetchall(): p("  named=%r n=%d" % r)

    # props count 分布：这是 u32@0 的候选
    p("=== props sample ===")
    cur.execute("SELECT props, COUNT(*) FROM resources WHERE type='scene' GROUP BY props ORDER BY 2 DESC LIMIT 30")
    for r in cur.fetchall(): p("  %r n=%d" % r)

    # 直接按 subtype 找 749：也许 subtype 里编码了 tag
    p("=== distinct subtype where type like scene-ish ===")
    cur.execute("SELECT type,subtype,COUNT(*) FROM resources WHERE ext='.scene' GROUP BY type,subtype ORDER BY 3 DESC")
    for r in cur.fetchall(): p("  %r %r %d" % r)

    # binary 那 1110 个是什么
    p("=== type=binary ext=.scene sample ===")
    cur.execute("SELECT hash,path,dir,name,subtype,ver,flags,method,stored,original,pak,gen,offset,named,props,src FROM resources WHERE ext='.scene' AND type='binary' LIMIT 8")
    cols=[d[0] for d in cur.description]
    for r in cur.fetchall(): p("  " + repr(r))

    con.close()
except Exception:
    p("FATAL:\n" + traceback.format_exc())

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("done")
