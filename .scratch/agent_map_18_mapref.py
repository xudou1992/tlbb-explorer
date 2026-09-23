import sqlite3, io, os, struct, collections, glob, re
c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
o=io.open('agent_map_18_mapref.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
rows=list(c.execute("select hash,path,original,occupied,pak,offset,src from resources where type='mapref' limit 10"))
W('mapref rows:',len(rows))
for r in rows[:6]: W(' ',r)
# locate payload on disk
def find(h):
    for pak in os.listdir('out/all'):
        d=os.path.join('out/all',pak)
        if not os.path.isdir(d): continue
        for fn in os.listdir(d):
            if fn.startswith(h): return os.path.join(d,fn)
got=0
for h,p,orig,occ,pak,off,src in rows:
    f=find(h)
    if not f: W('  no payload for',h); continue
    raw=open(f,'rb').read(); got+=1
    W('\n#### hash=%s path=%r size=%d orig=%s' % (h,p,len(raw),orig))
    if len(raw)>=8:
        W('   u32[0:8]',struct.unpack_from('<8I',raw,0))
        if len(raw)>=12: W('   f32[0:6] @8',[round(x,4) for x in struct.unpack_from('<6f',raw,8)])
    W('   hex[0:96]',raw[:96].hex(' '))
    S=[(m.start(),m.group().decode('latin1')) for m in re.finditer(rb'[\x20-\x7e]{5,}',raw)]
    W('   printable runs:',len(S),S[:8])
    W('   u32[1]==280? ', struct.unpack_from('<2I',raw,0)[1]==280 if len(raw)>=8 else None)
    if got>=8: break
W('\n== mapref size distribution')
for r in c.execute("select count(*),min(original),max(original),avg(original) from resources where type='mapref'"): W('  ',r)
o.close(); print('ok')
