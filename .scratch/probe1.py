import os, sqlite3, traceback

OUT = r"D:\TLGL\.scratch\probe1.txt"
lines = []

def p(*a):
    lines.append(" ".join(str(x) for x in a))

try:
    p("=== D:\\TLGL ===")
    for n in sorted(os.listdir(r"D:\TLGL")):
        fp = os.path.join(r"D:\TLGL", n)
        try:
            sz = os.path.getsize(fp) if os.path.isfile(fp) else -1
        except Exception:
            sz = -2
        p(f"  {n}  size={sz}")

    p("=== D:\\TLGL\\.scratch ===")
    for n in sorted(os.listdir(r"D:\TLGL\.scratch")):
        fp = os.path.join(r"D:\TLGL\.scratch", n)
        try:
            sz = os.path.getsize(fp) if os.path.isfile(fp) else -1
        except Exception:
            sz = -2
        p(f"  {n}  size={sz}")

    p("=== D:\\TLGL\\tlbb-explorer ===")
    for n in sorted(os.listdir(r"D:\TLGL\tlbb-explorer")):
        fp = os.path.join(r"D:\TLGL\tlbb-explorer", n)
        try:
            sz = os.path.getsize(fp) if os.path.isfile(fp) else -1
        except Exception:
            sz = -2
        p(f"  {n}  size={sz}")

    root = r"D:\TLGL\tlbb-explorer\crates"
    p("=== crates tree (depth<=3) ===")
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth > 3:
            dirnames[:] = []
            continue
        p(f"  [D] {dirpath}")
        for f in sorted(filenames):
            p(f"        {f}")

    # DB schema
    db = r"D:\TLGL\.scratch\resources.db"
    p("=== DB exists:", os.path.exists(db), "size:", os.path.getsize(db) if os.path.exists(db) else -1)
    con = sqlite3.connect("file:" + db.replace("\\", "/") + "?mode=ro", uri=True)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    p("=== TABLES ===")
    p("  " + ", ".join(tables))
    for t in tables:
        try:
            cur.execute(f"PRAGMA table_info('{t}')")
            cols = cur.fetchall()
            p(f"--- {t}: " + ", ".join(f"{c[1]}:{c[2]}" for c in cols))
        except Exception as e:
            p(f"--- {t} ERR {e}")
    con.close()
except Exception:
    p("FATAL:\n" + traceback.format_exc())

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("done")
