import sqlite3
con = sqlite3.connect(r"D:\TLGL\.scratch\resources.db")
c = con.cursor()
c.execute("select type, count(*) from resources where ext='.mdl' group by type")
rows = c.fetchall()
c.execute("select type, count(*) from resources where ext in ('.mesh','.ani','.ske','.mtl') group by type")
rows2 = c.fetchall()
c.execute("select name, type, ext from resources where ext='.mdl' and coalesce(name,'')<>'' limit 5")
samples = c.fetchall()
con.close()
with open(r"D:\TLGL\.scratch\mdl_types.txt", "w", encoding="utf-8") as f:
    f.write("ext=.mdl types: %r\n\nother types: %r\n\nsamples: %r" % (rows, rows2, samples))
print("done")
