import idc, ida_bytes, ida_funcs
out=open(r'D:/TLGL/.scratch/ida/tex_tables_out.txt','w',encoding='utf-8')
for base,name in [(0x14105be00,'LoadTexture/SizeByName'),(0x14105db00,'PreloadTexture'),(0x14106be00,'Atlas'),(0x141063c00,'GetTextureIcon'),(0x14104fd00,'GetTextureConvert')]:
    out.write('\n== %s @%x\n'%(name,base))
    for i in range(0,0x180,8):
        a=base+i
        q=ida_bytes.get_qword(a)
        tag=''
        if q and 0x140000000<=q<0x141400000:
            f=ida_funcs.get_func(q)
            tag=' CODE func=%s'%(hex(f.start_ea) if f else '?')
            if not f:
                # might be a string pointer
                try:
                    b=ida_bytes.get_bytes(q,16)
                    if b and all(32<=c<127 or c==0 for c in b):
                        tag+=' str=%r'%b.split(b'\0')[0]
                except: pass
        out.write('  %x: %016x%s\n'%(a,q,tag))
out.close()
idc.qexit(0)
