import ida_hexrays, ida_funcs, idautils, idc
addrs=[0x140643880,0x14064EE50,0x14065B1C0,0x140646190,0x140642000,0x140644000]
out=open(r'D:/TLGL/.scratch/ida/mesh_class_out.txt','w',encoding='utf-8')
for a in addrs:
    f=ida_funcs.get_func(a)
    out.write('\n\n===== %x func=%s size=%s =====\n'%(a, hex(f.start_ea) if f else '-', f.size() if f else '-'))
    if f:
        callees=set()
        for x in idautils.XrefsFrom(f.start_ea,0):
            if x.type in (16,17):
                g=ida_funcs.get_func(x.to)
                if g and g.start_ea!=f.start_ea: callees.add(hex(g.start_ea))
        out.write('callees: %s\n'%(' '.join(sorted(callees))))
    try:
        s=str(ida_hexrays.decompile(a))
        out.write(s[:80000])
    except Exception as e:
        out.write('DECOMP FAIL: %r\n'%e)
out.close()
idc.qexit(0)
