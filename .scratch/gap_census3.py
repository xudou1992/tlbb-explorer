import sqlite3
c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
print('== extless breakdown by type ==')
for r in c.execute("select type, count(*) from resources where ext is null or ext='' group by 1 order by 2 desc"): print('  ', r)
print('== nested .pak paths ==')
for r in c.execute("select path from resources where ext='.pak' limit 8"): print('  ', r[0])
print('== .anis ==')
for r in c.execute("select subtype, count(*) from resources where ext='.anis' group by 1"): print('  ', r)
