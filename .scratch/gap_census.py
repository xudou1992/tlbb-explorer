import sqlite3
c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
print('== total ==', c.execute("select count(*) from resources").fetchone()[0])
print('== columns ==', [r[1] for r in c.execute("PRAGMA table_info(resources)")])
print()
print('== by ext (top 60) ==')
for r in c.execute("select ext, count(*) n, sum(named) named from resources group by ext order by n desc limit 60"):
    print(f"{(r[0] or '(none)'):12s} {r[1]:7d} named={r[2]}")
print()
print('== by type ==')
for r in c.execute("select type, count(*) n from resources group by type order by n desc limit 40"):
    print(f"{(r[0] or '(none)'):12s} {r[1]:7d}")
print()
print('== type x ext for undecoded-looking types ==')
for r in c.execute("select type, ext, count(*) n from resources where type in ('geom','ani','Unknown','') or type is null group by 1,2 order by n desc limit 30"):
    print(f"{(r[0] or '(none)'):10s} {(r[1] or '(none)'):10s} {r[2]:7d}")
