import idc, ida_funcs, ida_hexrays, idautils
out=open(r'D:/TLGL/.scratch/ida/tex_mgr_out.txt','w',encoding='utf-8')
funcs=[0x140324590,0x140324650,0x140325090,0x140468DB0,0x140468E50,0x140324A60]
for a in funcs:
    f=ida_funcs.get_func(a)
    out.write('\n\n===== %x size=%s =====\n'%(a,f.size() if f else '-'))
    if f:
        cs=[]
        for x in idautils.XrefsFrom(f.start_ea,0):
            g=ida_funcs.get_func(x.to)
            if g and g.start_ea!=f.start_ea: cs.append(hex(g.start_ea))
        out.write('callees: %s\n'%(' '.join(sorted(set(cs)))))
    try: out.write(str(ida_hexrays.decompile(a))[:100000])
    except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
