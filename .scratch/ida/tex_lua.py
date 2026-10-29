import idc, ida_funcs, ida_hexrays, idautils, ida_bytes
out=open(r'D:/TLGL/.scratch/ida/tex_lua_out.txt','w',encoding='utf-8')
funcs=[0x1403c52b0,0x1403c5870,0x1403c5890,0x1403c5970,0x1403c42f0,0x1403c5250,0x1403c5590,0x1403c55f0,0x1403c5730]
for a in funcs:
    f=ida_funcs.get_func(a)
    out.write('\n\n===== %x size=%s =====\n'%(a,f.size() if f else '-'))
    if f:
        cs=[]
        for x in idautils.XrefsFrom(f.start_ea,0):
            g=ida_funcs.get_func(x.to)
            if g and g.start_ea!=f.start_ea: cs.append(hex(g.start_ea))
        out.write('callees: %s\n'%(' '.join(sorted(set(cs)))))
    try: out.write(str(ida_hexrays.decompile(a))[:80000])
    except Exception as e: out.write('FAIL %r\n'%e)
# locate PreloadTextureFile function: find xref to its string (data table)
s=0x140ecd578
for x in idautils.XrefsTo(s,0):
    out.write('\nPreloadTextureFile nameptr @%x\n'%x.frm)
    for off in (-8,8):
        q=ida_bytes.get_qword(x.frm+off)
        g=ida_funcs.get_func(q)
        out.write('  +%d: %x func=%s\n'%(off,q,hex(g.start_ea) if g else '-'))
        if g and off==-8:
            out.write(str(ida_hexrays.decompile(g.start_ea))[:60000])
out.close()
idc.qexit(0)
