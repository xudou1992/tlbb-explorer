import idc, ida_bytes, ida_funcs, idautils
out=open(r'D:/TLGL/.scratch/ida/segscan_out.txt','w',encoding='utf-8')
segs=list(idautils.Segments())
out.write('segs %d\n'%len(segs))
for seg in segs:
    st=idc.get_segm_start(seg); en=idc.get_segm_end(seg)
    name=idc.get_segm_name(seg)
    if not name.startswith('.text'): continue
    data=ida_bytes.get_bytes(st, en-st)
    out.write('seg %s %x..%x len=%d\n'%(name,st,en,len(data)))
    for pat in [b'Copy', b'Copyright 2013', b'Copyright']:
        i=0; hits=[]
        while True:
            i=data.find(pat,i)
            if i<0 or len(hits)>=20: break
            ea=st+i
            f=ida_funcs.get_func(ea)
            hits.append((ea, f.start_ea if f else 0))
            i+=1
        out.write('  %r %d %s\n'%(pat,len(hits),' '.join('%x(f=%x)'%h for h in hits)))
out.close()
idc.qexit(0)
