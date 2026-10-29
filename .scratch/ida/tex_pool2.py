import idc, ida_funcs, ida_hexrays, idautils
out=open(r'D:/TLGL/.scratch/ida/tex_pool2_out.txt','w',encoding='utf-8')
a=0x1406c6e90
f=ida_funcs.get_func(a)
out.write('===== %x size=%s =====\n'%(a,f.size() if f else '-'))
if f:
    cs=[]
    for x in idautils.XrefsFrom(f.start_ea,0):
        g=ida_funcs.get_func(x.to)
        if g and g.start_ea!=f.start_ea: cs.append(hex(g.start_ea))
    out.write('callees: %s\n'%(' '.join(sorted(set(cs)))))
    out.write('callers: %s\n'%(' '.join(hex(x.frm) for x in list(idautils.XrefsTo(f.start_ea,0))[:20])))
try: out.write(str(ida_hexrays.decompile(a))[:120000])
except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
