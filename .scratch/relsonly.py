import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
import dbbuild

con = dbbuild.sqlite3.connect(dbbuild.DB)
dbbuild.build_relations(con)
for row in con.execute("SELECT rel, COUNT(*) FROM relations GROUP BY rel"):
    print(row)
for row in con.execute("SELECT from_path, to_path, rel FROM relations WHERE rel='ref' LIMIT 5"):
    print(row)
