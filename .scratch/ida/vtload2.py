import idc, ida_bytes, ida_funcs, ida_hexrays
out=open(r'D:/TLGL/.scratch/ida/vtload2_out.txt','w',encoding='utf-8')
for name,va in [('MeshModel2',0x140ef6f10),('ModelST2',0x140ef68a0)]:
    out.write('===== %s vtable %x =====\n'%(name,va))
    for i in range(0,40):
        q=ida_bytes.get_qword(va+i*8)
        if q and 0x140000000<=q<0x141400000:
            f=ida_funcs.get_func(q)
            out.write(' +%d idx%d %x func=%s size=%s\n'%(i*8,i,q,hex(f.start_ea) if f else '-',f.size() if f else '-'))
    fn=ida_bytes.get_qword(va+96)
    out.write('\n===== %s +96 -> %x =====\n'%(name,fn))
    try:
        out.write(str(ida_hexrays.decompile(fn))[:120000])
    except Exception as e:
        out.write('FAIL %r\n'%e)
    out.write('\n\n')
out.close()
idc.qexit(0)
