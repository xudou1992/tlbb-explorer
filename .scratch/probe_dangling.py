"""Why do .tga references resolve only 25 times out of 30585?  Read-only."""
import sqlite3
import traceback

DB = r"D:\TLGL\.scratch\resources.db"
out = []
p = out.append

try:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    p("== dangling overview ==")
    p(f"  total rows: {cur.execute('SELECT COUNT(*) FROM dangling').fetchone()[0]}")
    p("  by ext:")
    for ext, n in cur.execute(
        "SELECT ext, COUNT(*) FROM dangling GROUP BY ext ORDER BY COUNT(*) DESC LIMIT 20"
    ):
        p(f"    {str(ext)!r:12} {n}")

    p("")
    p("== dangling .tga top names ==")
    for row in cur.execute(
        "SELECT name, n_refs, n_src, cls FROM dangling WHERE ext='.tga' "
        "ORDER BY n_refs DESC LIMIT 15"
    ):
        p(f"    {row}")

    p("")
    p("== name forms ==")
    p("  resources.name (.tga):")
    for (n,) in cur.execute("SELECT name FROM resources WHERE lower(ext)='.tga' LIMIT 6"):
        p(f"    {n!r}")
    p("  refs.name (.tga):")
    for (n,) in cur.execute("SELECT name FROM refs WHERE lower(kind)='.tga' LIMIT 6"):
        p(f"    {n!r}")

    p("")
    JOIN_EXACT = (
        "SELECT COUNT(*) FROM refs r WHERE lower(r.kind)=? "
        "AND EXISTS (SELECT 1 FROM resources x WHERE x.name = r.name)"
    )
    JOIN_CI = (
        "SELECT COUNT(*) FROM refs r WHERE lower(r.kind)=? "
        "AND EXISTS (SELECT 1 FROM resources x WHERE lower(x.name) = lower(r.name))"
    )
    JOIN_TAIL = (
        "SELECT COUNT(*) FROM refs r WHERE lower(r.kind)=? "
        "AND EXISTS (SELECT 1 FROM resources x WHERE lower(x.name) = "
        "lower(trim(replace(replace(r.name, '\\', '/'), rtrim(r.name, replace(r.name, '/', '')), ''))))"
    )

    p("== join tests: refs.name vs resources.name ==")
    p(f"  .tga exact:            {cur.execute(JOIN_EXACT, ('.tga',)).fetchone()[0]}")
    p(f"  .tga case-insensitive: {cur.execute(JOIN_CI, ('.tga',)).fetchone()[0]}")
    p("")
    p("== same test for .mtl, which DOES resolve 37779 times ==")
    p(f"  .mtl exact:            {cur.execute(JOIN_EXACT, ('.mtl',)).fetchone()[0]}")
    p(f"  .mtl case-insensitive: {cur.execute(JOIN_CI, ('.mtl',)).fetchone()[0]}")
    p("")
    p("== is the .tga a plain filename, or a path? ==")
    p(f"  refs .tga with '/' in name:  {cur.execute(chr(47).join(['SELECT COUNT(*) FROM refs WHERE lower(kind)=? AND instr(name, ', ') > 0']), ('.tga',)).fetchone()[0]}")
    p(f"  resources .tga with '/' in name: {cur.execute(chr(47).join(['SELECT COUNT(*) FROM resources WHERE lower(ext)=? AND instr(name, ', ') > 0']), ('.tga',)).fetchone()[0]}")
    p(f"  resources .tga with '/' in path: {cur.execute('SELECT COUNT(*) FROM resources WHERE lower(ext)=? AND instr(path, chr(47)) > 0', ('.tga',)).fetchone()[0]}")
    p("  sample resources .tga paths:")
    for (pp, nn) in cur.execute("SELECT path, name FROM resources WHERE lower(ext)='.tga' LIMIT 8"):
        p(f"    path={pp!r} name={nn!r}")

    p("")
    p("== sample .tga refs with to_hash state ==")
    for name, toh in cur.execute(
        "SELECT name, to_hash FROM refs WHERE lower(kind)='.tga' LIMIT 10"
    ):
        p(f"    {name!r:58} to={toh!r}")

    p("")
    p("== sample .tga refs that DID resolve ==")
    for name, toh, fp in cur.execute(
        "SELECT name, to_hash, from_path FROM refs "
        "WHERE lower(kind)='.tga' AND to_hash IS NOT NULL LIMIT 10"
    ):
        p(f"    {name!r:52} to={toh!r} from={fp!r}")

    con.close()
except Exception:
    p("EXCEPTION:")
    p(traceback.format_exc())

open(r"D:\TLGL\.scratch\probe_dangling.txt", "w", encoding="utf-8").write("\n".join(out))
print("written", len(out), "lines")
