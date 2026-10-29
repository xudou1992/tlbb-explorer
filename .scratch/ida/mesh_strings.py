import idautils, idc, ida_funcs, ida_bytes
out = open(r'D:/TLGL/.scratch/ida/mesh_strings_out.txt','w',encoding='utf-8')
seen=0
for s in idautils.Strings():
    try: t=str(s)
    except: continue
    low=t.lower()
    if 'mesh' not in low: continue
    if len(t)>90: continue
    xr=list(idautils.XrefsTo(s.ea,0))
    funcs=[]
    for x in xr[:8]:
        f=ida_funcs.get_func(x.frm)
        funcs.append(hex(f.start_ea) if f else hex(x.frm))
    out.write('%x\t%r\txrefs=%d\t%s\n'%(s.ea,t,len(xr),','.join(funcs)))
    seen+=1
    if seen>400: break
out.close()
idc.qexit(0)
