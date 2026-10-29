import idc, ida_funcs, ida_hexrays, idautils
out=open(r'D:/TLGL/.scratch/ida/tex_convert_init_out.txt','w',encoding='utf-8')
t=0x1401230B0
for x in idautils.XrefsTo(t,0):
    f=ida_funcs.get_func(x.frm)
    out.write('\ncaller %x func=%s\n'%(x.frm,hex(f.start_ea) if f else '-'))
    if f and f.size()<20000:
        try: out.write(str(ida_hexrays.decompile(f.start_ea))[:90000])
        except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
