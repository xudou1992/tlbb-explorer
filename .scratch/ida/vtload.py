import idc, ida_bytes, ida_funcs, ida_hexrays
out=open(r'D:/TLGL/.scratch/ida/vtload_out.txt','w',encoding='utf-8')
for name,va in [('MeshModel',0x140ef7068),('ModelST',0x140ef6408)]:
    out.write('===== %s vtable %x =====\n'%(name,va))
    for i in range(0,120):
        q=ida_bytes.get_qword(va+i*8)
        if q and 0x140000000<=q<0x141400000:
            f=ida_funcs.get_func(q)
            out.write(' +%d (idx %d) %x func=%s\n'%(i*8,i,q,hex(f.start_ea) if f else '-'))
    out.write('\n')
# decompile +264 targets
for name,va in [('MeshModel',0x140ef7068),('ModelST',0x140ef6408)]:
    fn=ida_bytes.get_qword(va+264)
    out.write('\n===== %s +264 -> %x =====\n'%(name,fn))
    try:
        out.write(str(ida_hexrays.decompile(fn))[:80000])
    except Exception as e:
        out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
