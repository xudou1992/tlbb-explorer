import idc, ida_funcs, ida_hexrays, idautils
out=open(r'D:/TLGL/.scratch/ida/tex_pool_out.txt','w',encoding='utf-8')
names=[]
for ea,name in idautils.Names():
    if 'TexturePool' in name or 'Texture2D' in name or 'TextureFileConverter' in name:
        names.append((ea,name))
out.write('names:\n')
for ea,name in names: out.write('  %x %s\n'%(ea,name))
# find any symbol exactly/near TexturePool_GetOrCreate
targets=set()
for ea,name in names:
    if 'GetOrCreate' in name or 'TexturePool' in name:
        f=ida_funcs.get_func(ea)
        if f: targets.add(f.start_ea)
out.write('targets: %s\n'%(' '.join(hex(x) for x in sorted(targets))))
for a in sorted(targets)[:8]:
    f=ida_funcs.get_func(a)
    out.write('\n\n===== %x size=%s =====\n'%(a,f.size() if f else '-'))
    if f:
        cs=[]
        for x in idautils.XrefsFrom(f.start_ea,0):
            g=ida_funcs.get_func(x.to)
            if g and g.start_ea!=f.start_ea: cs.append(hex(g.start_ea))
        out.write('callees: %s\n'%(' '.join(sorted(set(cs)))))
        out.write('callers: %s\n'%(' '.join(hex(x.frm) for x in idautils.XrefsTo(f.start_ea,0)[:10])))
    try: out.write(str(ida_hexrays.decompile(a))[:120000])
    except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
