import sqlite3, io, collections
c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
o=io.open('agent_map_15_hunt.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
names=['w1351_fh_qiangzhi_001.mesh','w1351_lyxj_dengta_001.mesh','w1351_bzd_hongshizhuqi_001.mesh','w1351_fh_shitiao_001.mesh']
for n in names:
    stem=n[:-5]
    W('\n#### %s'%n)
    W('  resources.path LIKE %%name%%:', list(c.execute("select hash,path from resources where lower(path) like ? limit 5",('%'+n.lower(),))))
    W('  refs.name =:', list(c.execute("select from_hash,from_path,kind,to_hash from refs where lower(name)=? limit 5",(n.lower(),))))
    W('  refs.name stem:', list(c.execute("select from_hash,from_path,name,kind from refs where lower(name)=? limit 5",(stem,))))
    W('  agroup_names:', list(c.execute("select gid,name,cls from agroup_names where lower(name) like ?",('%'+stem.lower()+'%',))))
    W('  dangling:', list(c.execute("select * from dangling where lower(name) like ?",('%'+stem.lower()+'%',))))
W('\n== unnamed resources by type/subtype')
for r in c.execute("select type,subtype,count(*) from resources where named=0 group by 1,2 order by 3 desc limit 20"): W(' ',r)
W('\n== how do we know an unnamed blob is a mesh?  count named=0 with type in mesh-ish')
for r in c.execute("select type,subtype,count(*),sum(original) from resources where named=0 group by 1,2 order by 3 desc limit 15"): W(' ',r)
W('\n== refs kind census')
for r in c.execute("select kind,count(*) from refs group by 1 order by 2 desc limit 15"): W(' ',r)
W('\n== sample refs rows from an mtl in mobile_maps_source')
for r in c.execute("select from_path,name,kind,to_hash from refs where from_path like 'mobile_maps_source/%' limit 12"): W(' ',r)
o.close(); print('ok')
