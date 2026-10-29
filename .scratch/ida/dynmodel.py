import idc, idautils, ida_funcs, ida_bytes, ida_hexrays
out=open(r'D:/TLGL/.scratch/ida/dynmodel_out.txt','w',encoding='utf-8')
targets=['DynModelShader','SkinModel','StaticMesh','StaticModelShader']
found={}
for s in idautils.Strings():
    t=str(s)
    if t in targets:
        found[t]=(s.ea,list(idautils.XrefsTo(s.ea,0)))
for t,(ea,xr) in found.items():
    out.write('== %s str@%x xrefs=%d\n'%(t,ea,len(xr)))
    funcs=set()
    for x in xr:
        f=ida_funcs.get_func(x.frm)
        if f: funcs.add(f.start_ea)
        out.write('   from %x func=%s\n'%(x.frm,hex(f.start_ea) if f else '-'))
    for f in sorted(funcs):
        out.write('\n----- func %x -----\n'%f)
        try: out.write(str(ida_hexrays.decompile(f))[:60000])
        except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
