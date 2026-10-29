import idc, ida_bytes, ida_funcs, ida_hexrays
out=open(r'D:/TLGL/.scratch/ida/es_load_out.txt','w',encoding='utf-8')
for nm in ['??_7EsTexture2D@@6B@','??_7EsTexture2D@@6B@_0']:
    va=idc.get_name_ea_simple(nm)
    out.write('\n== %s -> %x\n'%(nm,va))
    if not va: continue
    for i in range(0,20):
        q=ida_bytes.get_qword(va+i*8)
        if q and 0x140000000<=q<0x141400000:
            f=ida_funcs.get_func(q)
            out.write('  +%d idx%d %x func=%s size=%s\n'%(i*8,i,q,hex(f.start_ea) if f else '-',f.size() if f else '-'))
    fn=ida_bytes.get_qword(va+96)
    out.write('-- +96 -> %x\n'%fn)
    try: out.write(str(ida_hexrays.decompile(fn))[:120000])
    except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
