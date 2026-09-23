"""Why do .tga references resolve only 25 / 30585?  Read-only, plain SQL."""
import sqlite3
import traceback

DB = r"D:\TLGL\.scratch\resources.db"
out = []
p = out.append

Q = {
    "tga_exact":  "SELECT COUNT(*) FROM refs r WHERE lower(r.kind)='.tga' AND EXISTS (SELECT 1 FROM resources x WHERE x.name = r.name)",
    "tga_ci":     "SELECT COUNT(*) FROM refs r WHERE lower(r.kind)='.tga' AND EXISTS (SELECT 1 FROM resources x WHERE lower(x.name) = lower(r.name))",
    "mtl_exact":  "SELECT COUNT(*) FROM refs r WHERE lower(r.kind)='.mtl' AND EXISTS (SELECT 1 FROM resources x WHERE x.name = r.name)",
    "mtl_ci":     "SELECT COUNT(*) FROM refs r WHERE lower(r.kind)='.mtl' AND EXISTS (SELECT 1 FROM resources x WHERE lower(x.name) = lower(r.name))",
    "tga_ref_slash": "SELECT COUNT(*) FROM refs WHERE lower(kind)='.tga' AND instr(name,'/') > 0",
    "tga_res_slash": "SELECT COUNT(*) FROM resources WHERE lower(ext)='.tga' AND instr(path,'/') > 0",
    "tga_res_total": "SELECT COUNT(*) FROM resources WHERE lower(ext)='.tga'",
    "tga_empty_name": "SELECT COUNT(*) FROM resources WHERE lower(ext)='.tga' AND (name IS NULL OR name='')",
}

try:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    p("== join tests: refs.name vs resources.name ==")
    for k, sql in Q.items():
        p(f"  {k:16} {cur.execute(sql).fetchone()[0]}")

    p("")
    p("== sample resources .tga rows (the ~2259 we hold) ==")
    for row in cur.execute(
        "SELECT path, name, ext, width, height FROM resources WHERE lower(ext)='.tga' LIMIT 10"
    ):
        p(f"    {row}")

    p("")
    p("== sample refs .tga rows (the 30585 asked for) ==")
    for row in cur.execute(
        "SELECT name, kind, to_hash, from_path FROM refs WHERE lower(kind)='.tga' LIMIT 10"
    ):
        p(f"    {row}")

    p("")
    p("== do dangling .tga names exist as ANY resource? ==")
    sql = ("SELECT COUNT(*) FROM dangling d WHERE d.ext='.tga' "
           "AND EXISTS (SELECT 1 FROM resources x WHERE lower(x.name) = lower(d.name))")
    p(f"  dangling .tga whose name IS a resource: {cur.execute(sql).fetchone()[0]}")
    p("  samples that ARE present:")
    sql2 = ("SELECT d.name, x.ext, x.path FROM dangling d "
            "JOIN resources x ON lower(x.name) = lower(d.name) "
            "WHERE d.ext='.tga' LIMIT 10")
    for row in cur.execute(sql2):
        p(f"    {row}")

    con.close()
except Exception:
    p("EXCEPTION:")
    p(traceback.format_exc())

open(r"D:\TLGL\.scratch\probe_dangling2.txt", "w", encoding="utf-8").write("\n".join(out))
print("written")
