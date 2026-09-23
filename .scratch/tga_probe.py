import sqlite3, traceback
DB = r"D:\TLGL\.scratch\resources.db"
lines = []
try:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()
    tests = [
        ("tga_exact", "SELECT COUNT(*) FROM refs r WHERE lower(r.kind)='.tga' AND EXISTS (SELECT 1 FROM resources x WHERE x.name = r.name)"),
        ("tga_ci",    "SELECT COUNT(*) FROM refs r WHERE lower(r.kind)='.tga' AND EXISTS (SELECT 1 FROM resources x WHERE lower(x.name) = lower(r.name))"),
        ("mtl_exact", "SELECT COUNT(*) FROM refs r WHERE lower(r.kind)='.mtl' AND EXISTS (SELECT 1 FROM resources x WHERE x.name = r.name)"),
        ("mtl_ci",    "SELECT COUNT(*) FROM refs r WHERE lower(r.kind)='.mtl' AND EXISTS (SELECT 1 FROM resources x WHERE lower(x.name) = lower(r.name))"),
        ("tga_res_total", "SELECT COUNT(*) FROM resources WHERE lower(ext)='.tga'"),
        ("tga_empty_name", "SELECT COUNT(*) FROM resources WHERE lower(ext)='.tga' AND (name IS NULL OR name='')"),
        ("tga_res_have_slash", "SELECT COUNT(*) FROM resources WHERE lower(ext)='.tga' AND instr(path,'/')>0"),
        ("dangling_tga", "SELECT COUNT(*) FROM dangling WHERE ext='.tga'"),
        ("dangling_tga_is_res", "SELECT COUNT(*) FROM dangling d WHERE d.ext='.tga' AND EXISTS (SELECT 1 FROM resources x WHERE lower(x.name)=lower(d.name))"),
    ]
    for name, sql in tests:
        try:
            lines.append(f"{name:22} = {cur.execute(sql).fetchone()[0]}")
        except Exception as e:
            lines.append(f"{name:22} ! {e}")

    lines.append("")
    lines.append("-- sample resources .tga --")
    for row in cur.execute("SELECT path, name, ext, width, height FROM resources WHERE lower(ext)='.tga' LIMIT 6"):
        lines.append("   " + repr(row))
    lines.append("-- sample refs .tga --")
    for row in cur.execute("SELECT name, kind, to_hash, from_path FROM refs WHERE lower(kind)='.tga' LIMIT 6"):
        lines.append("   " + repr(row))
    lines.append("-- sample refs .mtl that RESOLVE --")
    for row in cur.execute("SELECT name, to_hash FROM refs WHERE lower(kind)='.mtl' AND to_hash IS NOT NULL LIMIT 6"):
        lines.append("   " + repr(row))
    con.close()
except Exception:
    lines.append("FATAL:")
    lines.append(traceback.format_exc())

with open(r"D:\TLGL\.scratch\tga_out.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
