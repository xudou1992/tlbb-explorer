import os, sqlite3, traceback, struct

OUT = r"D:\TLGL\.scratch\probe_sc1.txt"
lines = []
def p(*a): lines.append(" ".join(str(x) for x in a))

db = r"D:\TLGL\.scratch\resources.db"
try:
    con = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)
    cur = con.cursor()

    p("=== type='scene' rows sample ===")
    cur.execute("SELECT hash,path,dir,name,ext,type,subtype,codec,ver,flags,method,stored,occupied,original,filecrc,pak,gen,offset,named,props,src,self_path FROM resources WHERE type='scene' LIMIT 6")
    cols=[d[0] for d in cur.description]
    p("  cols: " + ",".join(cols))
    for r in cur.fetchall():
        for c,v in zip(cols,r): p("      %s=%r" % (c,v))
        p("      ---")

    p("=== type='scene' path samples ===")
    cur.execute("SELECT path FROM resources WHERE type='scene' ORDER BY path LIMIT 40")
    for r in cur.fetchall(): p("  " + str(r[0]))

    p("=== type='scene' dir distribution ===")
    cur.execute("SELECT dir, COUNT(*) FROM resources WHERE type='scene' GROUP BY dir ORDER BY 2 DESC LIMIT 30")
    for r in cur.fetchall(): p("  dir=%r n=%d" % r)

    p("=== type='scene' subtype distribution ===")
    cur.execute("SELECT subtype, COUNT(*) FROM resources WHERE type='scene' GROUP BY subtype ORDER BY 2 DESC")
    for r in cur.fetchall(): p("  subtype=%r n=%d" % r)

    p("=== type='scene' pak distribution ===")
    cur.execute("SELECT pak, COUNT(*) FROM resources WHERE type='scene' GROUP BY pak ORDER BY 2 DESC LIMIT 20")
    for r in cur.fetchall(): p("  pak=%r n=%d" % r)

    p("=== size stats type='scene' (stored/original) ===")
    cur.execute("SELECT MIN(stored),MAX(stored),MIN(original),MAX(original),COUNT(*) FROM resources WHERE type='scene'")
    p("  " + repr(cur.fetchone()))

    p("=== all ext='.scene' rows grouped by type ===")
    cur.execute("SELECT type, COUNT(*) FROM resources WHERE ext='.scene' GROUP BY type")
    for r in cur.fetchall(): p("  %r %d" % r)

    con.close()
except Exception:
    p("FATAL:\n" + traceback.format_exc())

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("done")
