import idc, ida_funcs, ida_hexrays, idautils, ida_bytes
out=open(r'D:/TLGL/.scratch/ida/tex_mgr2_out.txt','w',encoding='utf-8')
funcs=[0x140325AA0,0x140325B40,0x1401230B0]
# Lua table entry for GetTextureConvertInformation: nameptr at 0x14104fd98 -> func at -8
for nameptr in [0x14104fd98]:
    q=ida_bytes.get_qword(nameptr-8)
    f=ida_funcs.get_func(q)
    if f: funcs.append(f.start_ea)
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
