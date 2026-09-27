import os, sqlite3, traceback

OUT = r"D:\TLGL\.scratch\probe_sc0.txt"
lines = []
def p(*a): lines.append(" ".join(str(x) for x in a))

db = r"D:\TLGL\.scratch\resources.db"
try:
    con = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)
    cur = con.cursor()

    p("=== resources type/subtype counts where ext has scene ===")
    cur.execute("SELECT type, subtype, ext, COUNT(*) FROM resources WHERE lower(ext) LIKE '%scene%' GROUP BY type, subtype, ext ORDER BY 4 DESC")
    for r in cur.fetchall(): p("  type=%r subtype=%r ext=%r n=%d" % r)

    p("=== distinct ext values ===")
    cur.execute("SELECT ext, COUNT(*) FROM resources GROUP BY ext ORDER BY 2 DESC LIMIT 50")
    for r in cur.fetchall(): p("  ext=%r n=%d" % r)

    p("=== total resources ===")
    cur.execute("SELECT COUNT(*) FROM resources")
    p("  " + str(cur.fetchone()[0]))

    p("=== scene rows sample ===")
    cur.execute("SELECT * FROM resources WHERE lower(ext) LIKE 'scene' LIMIT 5")
    cols = [d[0] for d in cur.description]
    p("  cols: " + ",".join(cols))
    for r in cur.fetchall(): p("  " + repr(r))

    p("=== scene path samples ===")
    cur.execute("SELECT path FROM resources WHERE lower(ext) LIKE 'scene' ORDER BY path LIMIT 40")
    for r in cur.fetchall(): p("  " + str(r[0]))

    p("=== scene count with pak empty / offset weird ===")
    cur.execute("SELECT COUNT(*) FROM resources WHERE lower(ext)='scene'")
    n = cur.fetchone()[0]
    p("  total scene: %d" % n)
    if n:
        cur.execute("SELECT COUNT(*) FROM resources WHERE lower(ext)='scene' AND (pak IS NULL OR pak='')")
        p("  pak empty: %d" % cur.fetchone()[0])
        cur.execute("SELECT MIN(offset), MAX(offset), MIN(stored), MAX(stored), MIN(original), MAX(original) FROM resources WHERE lower(ext)='scene'")
        p("  offset/stored/original minmax: " + repr(cur.fetchone()))

    p("=== meta ===")
    cur.execute("SELECT key, value FROM meta")
    for r in cur.fetchall(): p("  %s = %s" % r)

    p("=== records sample ===")
    cur.execute("SELECT * FROM records LIMIT 3")
    p("  cols: " + ",".join(d[0] for d in cur.description))
    for r in cur.fetchall(): p("  " + repr(r))

    con.close()
except Exception:
    p("FATAL:\n" + traceback.format_exc())

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("done")
