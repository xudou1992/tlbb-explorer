import idc, ida_bytes, idautils, ida_funcs
out=open(r'D:/TLGL/.scratch/ida/dynload_scan_out.txt','w',encoding='utf-8')
# find the string address first
ea=0x140f1ba30
for name,size,base in [('va',8,ea),('rva',4,(ea-0x140000000)&0xFFFFFFFF)]:
    pat=base.to_bytes(size,'little'); hits=0
    out.write('== %s %x\n'%(name,base))
    for seg in idautils.Segments():
        st=idc.get_segm_start(seg); en=idc.get_segm_end(seg)
        data=ida_bytes.get_bytes(st,en-st)
        i=0
        while True:
            i=data.find(pat,i)
            if i<0 or hits>=15: break
            a=st+i
            f=ida_funcs.get_func(a)
            out.write('  at %x seg=%s func=%s ctx='%(a,idc.get_segm_name(seg),hex(f.start_ea) if f else '-'))
            out.write(' '.join('%016x'%ida_bytes.get_qword(a-16+k*8) for k in range(4)))
            out.write('\n'); hits+=1; i+=1
        if hits>=15: break
out.close()
idc.qexit(0)
