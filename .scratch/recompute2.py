import sqlite3, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbbuild
con = sqlite3.connect(dbbuild.DB, timeout=180)
con.execute('PRAGMA busy_timeout=180000')
dbbuild.build_relations(con)
dbbuild.build_asset_groups(con)
con.close()
