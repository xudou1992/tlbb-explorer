import idc, ida_bytes, ida_funcs, ida_hexrays, idautils
out=open(r'D:/TLGL/.scratch/ida/es_texture_out.txt','w',encoding='utf-8')
vs=[]
for ea,name in idautils.Names():
    if 'EsTexture2D' in name:
        out.write('%x %s\n'%(ea,name))
        if 'vftable' in name: vs.append((ea,name))
out.write('\nvtables: %s\n'%vs)
for va,name in vs[:4]:
    out.write('\n== vtable %x %s\n'%(va,name))
    for i in range(0,30):
        q=ida_bytes.get_qword(va+i*8)
        if q and 0x140000000<=q<0x141400000:
            f=ida_funcs.get_func(q)
            out.write('  +%d idx%d %x func=%s size=%s\n'%(i*8,i,q,hex(f.start_ea) if f else '-',f.size() if f else '-'))
    # decompile +96
    fn=ida_bytes.get_qword(va+96)
    out.write('\n-- +96 -> %x\n'%fn)
    try: out.write(str(ida_hexrays.decompile(fn))[:100000])
    except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
