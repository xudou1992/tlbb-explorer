import os, sqlite3, json, collections

OUT = r"D:\TLGL\.scratch\probe_sc3.txt"
lines = []
def p(*a): lines.append(" ".join(str(x) for x in a))

db = r"D:\TLGL\.scratch\resources.db"
con = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)
cur = con.cursor()

# 所有 .scene 行的 props 头部三元组分布
p("=== all .scene rows: props shape ===")
cur.execute("SELECT type, COUNT(*) FROM resources WHERE ext='.scene' GROUP BY type")
for r in cur.fetchall(): p("  %r %d" % r)

# type=scene 的 props 是 {"count": N}；type=binary 的是 {"f": [a,b,c,d]}
p("=== type=binary .scene: f[0] vs f[1] pairs ===")
cur.execute("SELECT props FROM resources WHERE ext='.scene' AND type='binary'")
tagcnt = collections.Counter()
gap = collections.Counter()
n = 0
mal = 0
for (pr,) in cur.fetchall():
    try:
        d = json.loads(pr)
        f = d.get("f")
        if not f or len(f) < 2:
            mal += 1
            continue
        n += 1
        tagcnt[f[1]] += 1
    except Exception:
        mal += 1
p("  parsed=%d malformed=%d" % (n, mal))
p("  tag(f[1]) distribution: " + repr(tagcnt.most_common(20)))

p("=== type=scene props count distribution summary ===")
cur.execute("SELECT props FROM resources WHERE ext='.scene' AND type='scene'")
cs = []
for (pr,) in cur.fetchall():
    try: cs.append(json.loads(pr)["count"])
    except Exception: pass
p("  n=%d min=%d max=%d" % (len(cs), min(cs), max(cs)))

# 关键：把 749 的文件全列出来（type=binary 且 f[1]==749）
p("=== ALL binary .scene with f[1]==749 ===")
cur.execute("SELECT hash,path,stored,original,pak,gen,offset,props FROM resources WHERE ext='.scene' AND type='binary'")
rows749 = []
rows753 = []
for h,path,stored,orig,pak,gen,off,pr in cur.fetchall():
    try: f = json.loads(pr)["f"]
    except Exception: continue
    if f[1] == 749: rows749.append((h,path,stored,orig,pak,gen,off,f))
    elif f[1] == 753: rows753.append((h,path,stored,orig,pak,gen,off,f))
p("  count749=%d count753=%d" % (len(rows749), len(rows753)))
for r in rows749[:25]: p("    749 " + repr(r))
p("  ...")
for r in rows753[:25]: p("    753 " + repr(r))

# 全库 tag 分布：type=scene 的 753 + type=binary 的 f[1]
p("=== global tag census (type=scene => 753; type=binary => f[1]) ===")
cur.execute("SELECT COUNT(*) FROM resources WHERE ext='.scene' AND type='scene'")
p("  grid753 rows = %d" % cur.fetchone()[0])
for t,c in sorted(tagcnt.items()):
    p("  tag %s -> %d" % (t, c))

con.close()
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("done")
