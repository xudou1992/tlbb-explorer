import idc, ida_funcs, ida_hexrays, idautils
out=open(r'D:/TLGL/.scratch/ida/tex_trace3_out.txt','w',encoding='utf-8')
# callers of JMT1 dispatcher
for target in [0x14085F340,0x1409BBE70]:
    out.write('\n== xrefs to %x\n'%target)
    for x in idautils.XrefsTo(target,0):
        g=ida_funcs.get_func(x.frm)
        out.write('  %x func=%s\n'%(x.frm,hex(g.start_ea) if g else '-'))
# decompile name builder and dispatcher
for a in [0x14063D620,0x14085F340]:
    f=ida_funcs.get_func(a)
    out.write('\n\n===== %x size=%s =====\n'%(a,f.size() if f else '-'))
    try: out.write(str(ida_hexrays.decompile(a))[:100000])
    except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
