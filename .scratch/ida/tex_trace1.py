import idc, ida_funcs, ida_hexrays, idautils
out=open(r'D:/TLGL/.scratch/ida/tex_trace1_out.txt','w',encoding='utf-8')
addrs=[0x14085F270,0x14085F370,0x14085F740,0x1409BBE70]
for a in addrs:
    f=ida_funcs.get_func(a)
    out.write('\n\n===== %x size=%s =====\n'%(a,f.size() if f else '-'))
    out.write('callers:\n')
    for x in idautils.XrefsTo(a,0):
        g=ida_funcs.get_func(x.frm)
        out.write('  %x func=%s\n'%(x.frm,hex(g.start_ea) if g else '-'))
    try: out.write(str(ida_hexrays.decompile(a))[:80000])
    except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
