import sqlite3
DB = r"D:\TLGL\.scratch\resources.db"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = con.cursor()
out = []
for (name, sql) in cur.execute(
    "SELECT name, sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
):
    out.append(f"--- {name}")
    out.append(sql or "(view)")
    out.append("")
con.close()
open(r"D:\TLGL\.scratch\schema.txt", "w", encoding="utf-8").write("\n".join(out))
print("ok")
