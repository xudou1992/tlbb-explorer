import idc, ida_bytes, ida_funcs, ida_hexrays, idautils
out=open(r'D:/TLGL/.scratch/ida/tex_trace2_out.txt','w',encoding='utf-8')
# 1) data around Lua binding name strings
for name,ea in [('LoadTextureFileInformation',0x140ecb6d8),('GetTextureSizeByName',0x140ecb6c0),('PreloadTextureFile',0x140ecd578),('GetTextureFile',0x140ed07f0),('GetTextureName',0x140ed07e0),('GetTextureAtlasFile',0x140ed4ab8)]:
    out.write('\n== %s @%x\n'%(name,ea))
    base=ea-0x40
    for i in range(0,0x100,8):
        a=base+i
        q=ida_bytes.get_qword(a)
        tag=''
        if q and 0x140000000<=q<0x141400000:
            f=ida_funcs.get_func(q)
            tag=' CODE func=%s'%(hex(f.start_ea) if f else '?')
        out.write('  %x: %016x%s\n'%(a,q,tag))
# 2) material loader at the LoadFromBinMtlFile string xref
a=0x140612130
f=ida_funcs.get_func(a)
out.write('\n===== material loader func %x size=%s =====\n'%(f.start_ea if f else a, f.size() if f else '-'))
try: out.write(str(ida_hexrays.decompile(f.start_ea if f else a))[:120000])
except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
