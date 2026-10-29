import idc, idautils, ida_funcs, ida_bytes
out=open(r'D:/TLGL/.scratch/ida/vdecl_out.txt','w',encoding='utf-8')
want={'a_texCoord','a_tex0','a_position','a_Normal','a_color','a_costomize','s_baseMap','s_baseMap0','s_maskMap'}
for s in idautils.Strings():
    t=str(s)
    if t in want:
        xr=list(idautils.XrefsTo(s.ea,0))
        out.write('== %s @%x xrefs=%d\n'%(t,s.ea,len(xr)))
        for x in xr[:10]:
            f=ida_funcs.get_func(x.frm)
            out.write('   %x func=%s\n'%(x.frm,hex(f.start_ea) if f else '-'))
        # dump 16 qwords around the string (may be a descriptor table)
        base=s.ea-0x40
        out.write('   data around: '+' '.join('%x:%x'%(a,ida_bytes.get_qword(a)) for a in range(base, s.ea+0x80, 8))+'\n')
out.close()
idc.qexit(0)
