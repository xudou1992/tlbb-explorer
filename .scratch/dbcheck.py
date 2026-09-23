import sqlite3

con = sqlite3.connect(r'D:\TLGL\.scratch\resources.db')
q = lambda s: [print('  ', r) for r in con.execute(s)]
print('== provenance ==')
q("SELECT src, COUNT(*) FROM resources WHERE named=1 GROUP BY src ORDER BY 2 DESC")
print('== types by size ==')
q("SELECT type, COUNT(*), printf('%.2f',SUM(original)/1e9) FROM resources "
  "GROUP BY type ORDER BY 3 DESC LIMIT 12")
print('== named coverage by type ==')
q("SELECT type, SUM(named), COUNT(*) FROM resources GROUP BY type ORDER BY COUNT(*) DESC LIMIT 12")
print('== texture sizes ==')
q("SELECT codec, COUNT(*), MIN(width||'x'||height), MAX(width||'x'||height) FROM resources "
  "WHERE type='texture' GROUP BY codec")
print('== biggest named dirs ==')
q("SELECT dir, COUNT(*) FROM resources WHERE named=1 GROUP BY dir ORDER BY 2 DESC LIMIT 6")
print('== relations sample ==')
q("SELECT rel, COUNT(*) FROM relations GROUP BY rel")
q("SELECT r.rel, a.path, b.path FROM relations r JOIN resources a ON a.hash=r.from_hash "
  "JOIN resources b ON b.hash=r.to_hash WHERE rel='model-part' LIMIT 4")
