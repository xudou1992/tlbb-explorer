import numpy as np, struct, io, os, glob, re, sqlite3, collections
o=io.open('agent_map_21_table.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')
NAMEOK=re.compile(rb'^[A-Za-z0-9_\-\.]{4,80}$')
c=sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro',uri=True)
meta={}
for h,p,orig,type_,sub in c.execute("select hash,path,original,type,subtype from resources where named=1"):
    meta.setdefault(p.rsplit('/',1)[-1].lower(),(h,p,orig,type_,sub))
# mesh geometry counts from tree payloads
SRCDIR='out/tree/mobile_maps_source'
geo={}
def geom(name):
    k=name.lower()
    if k in geo: return geo[k]
    p=os.path.join(SRCDIR,k)
    r=None
    if os.path.exists(p):
        with open(p,'rb') as fh: h=fh.read(0x98)
        if len(h)>=0x98: r=(struct.unpack_from('<II',h,0x8C))
    geo[k]=r; return r
maps=['w1351_ll_dl_002','w1351_ll_loulan_001','w1351_fb_jiehun_001','w1351_ll_qingyuan_001','w1351_gj_jz_001','w1351_ll_cs_001','w1351_fb_sxzc_001']
W('%-24s %7s %8s %8s %8s %9s %10s %9s  %s'%('MAP','files','inst','uniq','reslv','trisUni','trisInst','bbox','mapfile'))
for m in maps:
    fs=sorted(glob.glob('out/tree/mobile_maps/%s/*.scene'%m))
    inst=0; uniq=set(); res=set(); tri_i=0; pts=[]; noname=0; nrec=0
    for f in fs:
        raw=open(f,'rb').read()
        if len(raw)<12: continue
        N,RS,Z=struct.unpack_from('<III',raw,0)
        if RS!=753: continue
        for i in range(N):
            b=12+761*i
            if b+65>len(raw): break
            nrec+=1
            nm=raw[b+64:b+64+697].split(b'\0',1)[0]
            if not NAMEOK.match(nm): noname+=1; continue
            s=nm.decode('latin1').lower()
            mat=struct.unpack_from('<16f',raw,b); pts.append((mat[12],mat[13],mat[14]))
            if s.endswith('.mesh'):
                uniq.add(s)
                if s in meta: res.add(s)
                g=geom(s)
                if g and s in res: tri_i+=g[1]
    tu=0
    for s in res:
        g=geom(s)
        if g: tu+=g[1]
    P=np.array(pts); u=len(uniq); r=len(res)
    W('%-24s %7d %8d %8d %8d %9d %10d %9s  %s'%(m,len(fs),nrec,u,r,
      tu,tri_i,'x%.0f..%.0f z%.0f..%.0f y%.0f..%.0f'%(P[:,0].min(),P[:,0].max(),P[:,2].min(),P[:,2].max(),np.percentile(P[:,1],1),np.percentile(P[:,1],99)) if len(P) else '-',
      '%s (%.1fMB)'%(os.path.basename(glob.glob('out/tree/mobile_maps/%s/*.map'%m)[0]),os.path.getsize(glob.glob('out/tree/mobile_maps/%s/*.map'%m)[0])/1e6) if glob.glob('out/tree/mobile_maps/%s/*.map'%m) else 'none'))
    W('     uniq-mesh resolve %.1f%%  missing uniq %d  unparseable rec %d  instance-tri/uniq-tri=%.1f  mesh files on disk in source dir: %d/%d'%(
      100.0*r/u,u-len(res),noname,tri_i/max(1,tu),sum(1 for s in uniq if os.path.exists(os.path.join(SRCDIR,s))),u))
W('\n== how many named .mesh live under mobile_maps_source and are present in tree?')
rows=[p for (h,p,orig,t,s) in meta.values() if p.rsplit('/',1)[-1].lower().endswith('.mesh')]
W('  named .mesh total:',len(rows),' in mobile_maps_source:',sum(1 for p in rows if p.startswith('mobile_maps_source')))
W('  tree files present:',sum(1 for p in rows if os.path.exists('out/tree/'+p)))
o.close(); print('ok')
