import idc, ida_funcs, ida_hexrays
out=open(r'D:/TLGL/.scratch/ida/vbuf_out.txt','w',encoding='utf-8')
for a in [0x140645FC0,0x140642A40,0x140642B20,0x140642C40,0x14063A7B0]:
    f=ida_funcs.get_func(a)
    out.write('\n===== %x size=%s =====\n'%(a,f.size() if f else '-'))
    try: out.write(str(ida_hexrays.decompile(a))[:90000])
    except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
