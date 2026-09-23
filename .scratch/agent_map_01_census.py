import sqlite3, io, collections
c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
o = io.open('agent_map_01_census.txt', 'w', encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a) + '\n')

W('== total resources', c.execute('select count(*) from resources').fetchone()[0])
W('\n== top 40 ext (all resources)')
for e, n in c.execute("select ifnull(ext,'(null)') e, count(*) n from resources group by e order by n desc limit 40"):
    W('%-14s %8d' % (e, n))

W('\n== top 40 dir (all resources)')
for d, n in c.execute("select ifnull(dir,'(null)') d, count(*) n from resources group by d order by n desc limit 40"):
    W('%-60s %8d' % (d, n))

W('\n== ext for paths matching map/scene/terrain keywords')
for e, n in c.execute("""select ifnull(ext,'(null)') e, count(*) n from resources
  where lower(path) like '%map%' or lower(path) like '%scene%' or lower(path) like '%terrain%'
  group by e order by n desc limit 40"""):
    W('%-14s %8d' % (e, n))

W('\n== type/subtype distribution for .scene/.map/.ter')
for r in c.execute("""select ext, type, subtype, codec, count(*) from resources
  where ext in ('scene','map','ter','mob','lmt','msh','are','ide','gam')
  group by 1,2,3,4 order by 5 desc limit 60"""):
    W(r)

W('\n== top dirs containing map/scene/terrain')
for d, n in c.execute("""select ifnull(dir,'(null)') d, count(*) n from resources
  where lower(path) like '%map%' or lower(path) like '%scene%' or lower(path) like '%terrain%'
  group by d order by n desc limit 50"""):
    W('%-60s %8d' % (d, n))

W('\n== named flag distribution')
for r in c.execute("select named, count(*) from resources group by 1"): W(r)
o.close(); print('ok')
