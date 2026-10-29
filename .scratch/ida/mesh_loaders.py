import ida_hexrays, ida_funcs, idautils, idc
addrs=[0x140721ba0,0x140724bf0,0x1407263f0,0x140782990,0x1407836d0,0x1405e6850,0x1405e8360,0x140646190]
out=open(r'D:/TLGL/.scratch/ida/mesh_loaders_out.txt','w',encoding='utf-8')
for a in addrs:
    f=ida_funcs.get_func(a)
    out.write('\n\n===== %x func=%s size=%s =====\n'%(a, hex(f.start_ea) if f else '-', f.size() if f else '-'))
    if f:
        callees=[]
        for x in idautils.XrefsFrom(f.start_ea,0):
            g=ida_funcs.get_func(x.to)
            if g and g.start_ea!=f.start_ea:
                callees.append(hex(g.start_ea))
        out.write('callees: %s\n'%(' '.join(sorted(set(callees)))))
    try:
        s=str(ida_hexrays.decompile(a))
        out.write(s[:60000])
    except Exception as e:
        out.write('DECOMP FAIL: %r\n'%e)
out.close()
idc.qexit(0)
