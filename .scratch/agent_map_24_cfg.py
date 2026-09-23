import io,re,struct,sqlite3,collections
o=io.open('agent_map_24_cfg.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
raw=open('out/tree/ResourcePath.cfg','rb').read()
W('cfg size',len(raw),'hdr',struct.unpack_from('<8I',raw,0))
for name in ['w1351_fh_qiangzhi_001','w1351_lyxj_shitouque_001']:
    i=raw.find(name.encode())
    W('\n#### first hit for %s at %d'%(name,i))
    W('   context:',raw[max(0,i-64):i+96])
S=[m.group().decode('latin1') for m in re.finditer(rb'[\x20-\x7e]{5,}\x00',raw)]
W('\ntotal NUL-terminated printable strings:',len(S))
W('  ending with .mesh:',sum(1 for s in S if s.endswith('.mesh')))
W('  containing lyxj:',sum(1 for s in S if 'lyxj' in s))
W('  sample lyxj:',[s for s in S if 'lyxj' in s][:8])
W('  sample .mesh:',[s for s in S if s.endswith('.mesh')][:8])
c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
W('\ndb: paths containing lyxj:', c.execute("select count(*) from resources where lower(path) like '%lyxj%'").fetchone())
for r in c.execute("select hash,path from resources where lower(path) like '%lyxj%' limit 6"): W('  ',r)
W('db: paths containing fh_qiangzhi:', c.execute("select count(*) from resources where lower(path) like '%qiangzhi%'").fetchone())
for r in c.execute("select hash,path,type from resources where lower(path) like '%qiangzhi%' limit 6"): W('  ',r)
# how many cfg .mesh strings are absent from resources.path basenames
bn=set()
for (p,) in c.execute("select path from resources where named=1"): bn.add(p.rsplit('/',1)[-1].lower())
ms=[s for s in S if s.endswith('.mesh')]
absent=[s for s in ms if s.lower() not in bn]
W('\ncfg .mesh strings: %d ; absent from resources.path basename: %d (%.1f%%)'%(len(ms),len(absent),100.0*len(absent)/len(ms)))
W('  absent examples:',absent[:15])
# and: do those absent names exist anywhere as a *file* in the tree?
import os
hits=0
for s in absent[:200]:
    for base in ('out/tree/mobile_maps_source','out/tree/data'):
        pass
pres=[s for s in absent[:400] if os.path.exists('out/tree/mobile_maps_source/'+s)]
W('  absent-by-db but file exists in mobile_maps_source: %d/%d'%(len(pres),min(400,len(absent))), pres[:6])
o.close(); print('ok')
