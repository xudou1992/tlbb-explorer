import sqlite3
c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
for r in c.execute("select hash, width, height, codec, original from resources where type='texture' and named=0 order by original desc limit 3"):
    print(r)
