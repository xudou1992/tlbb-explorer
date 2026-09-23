import sqlite3, io, collections
c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
o = io.open('agent_map_02_paths.txt', 'w', encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a) + '\n')

W('== top-level (first 2 path components) distribution for named resources')
cnt = collections.Counter()
for (p,) in c.execute("select path from resources where named=1"):
    parts = p.lower().split('/')
    cnt['/'.join(parts[:2]) if len(parts) > 1 else '(root)'] += 1
for k, v in cnt.most_common(40): W('%-50s %8d' % (k, v))

W('\n== .scene : sample 30 paths + sizes')
for r in c.execute("select path, original, occupied, type, subtype, codec from resources where ext='.scene' order by original desc limit 30"):
    W(r)
W('\n== .scene size stats')
W(c.execute("select count(*), sum(original), min(original), max(original), avg(original) from resources where ext='.scene'").fetchone())

W('\n== .map : ALL paths + sizes')
for r in c.execute("select path, original, occupied, type, subtype, codec, hash from resources where ext='.map' order by original desc"):
    W(r)
W('\n== .map size stats')
W(c.execute("select count(*), sum(original), min(original), max(original) from resources where ext='.map'").fetchone())

W('\n== .nav / .sfl sample')
for r in c.execute("select path, original, ext from resources where ext in ('.nav') order by original desc limit 30"): W(r)
for r in c.execute("select path, original from resources where ext='.sfl' order by original desc limit 10"): W(r)

W('\n== distinct type/subset for .scene and .map')
for r in c.execute("select ext, type, subtype, codec, count(*) from resources where ext in ('.scene','.map','.nav','.sfl') group by 1,2,3,4"): W(r)

W('\n== mobile_maps vs mobile_maps_source counts by ext')
for r in c.execute("select substr(dir,1,11) d, ext, count(*), sum(original) from resources where dir like 'mobile_maps%' group by 1,2 order by 1,3 desc"): W(r)

W('\n== how many map root dirs under mobile_maps')
W(c.execute("select count(distinct substr(dir,1,instr(dir||'/','/')-1)) from resources where dir like 'mobile_maps/%'").fetchone())
for r in c.execute("select count(distinct dir) from resources where dir like 'mobile_maps/%'"): W('distinct mobile_maps/* dirs:', r)
o.close(); print('ok')
