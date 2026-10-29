import idc, ida_funcs, ida_hexrays, idautils
out=open(r'D:/TLGL/.scratch/ida/resload_out.txt','w',encoding='utf-8')
for a in [0x1409A5EC0]:
    f=ida_funcs.get_func(a)
    out.write('\n===== %x size=%s =====\n'%(a,f.size() if f else '-'))
    if f:
        callees=set()
        for x in idautils.XrefsFrom(f.start_ea,0):
            g=ida_funcs.get_func(x.to)
            if g and g.start_ea!=f.start_ea: callees.add(hex(g.start_ea))
        out.write('callees: %s\n'%(' '.join(sorted(callees))))
    try: out.write(str(ida_hexrays.decompile(a))[:60000])
    except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
