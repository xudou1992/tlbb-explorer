import idc, ida_bytes, idautils
out=open(r'D:/TLGL/.scratch/ida/vdecl_rva_out.txt','w',encoding='utf-8')
targets={'a_position':0x140f15878,'a_texCoord':0x140f15820,'a_Normal':0x140f158b0,'a_color':0x140f158d0,'a_costomize':0x140f158c0,'a_tex0':0x140f15954}
for name,ea in targets.items():
    rva=(ea-0x140000000)&0xFFFFFFFF
    pat=rva.to_bytes(4,'little')
    out.write('== %s rva=%x\n'%(name,rva))
    hits=0
    for seg in idautils.Segments():
        st=idc.get_segm_start(seg); en=idc.get_segm_end(seg)
        data=ida_bytes.get_bytes(st,en-st)
        i=0
        while True:
            i=data.find(pat,i)
            if i<0 or hits>=10: break
            a=st+i
            out.write('  at %x %s ctx32='%(a,idc.get_segm_name(seg)))
            out.write(' '.join('%08x'%ida_bytes.get_dword(a-16+k*4) for k in range(0,12)))
            out.write('\n')
            hits+=1;i+=1
        if hits>=10: break
out.close()
idc.qexit(0)
