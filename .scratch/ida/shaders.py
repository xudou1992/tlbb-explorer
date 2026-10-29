import idc, ida_funcs, ida_hexrays
out=open(r'D:/TLGL/.scratch/ida/shaders_out.txt','w',encoding='utf-8')
for a in [0x140602A00,0x1406E3B30]:
    f=ida_funcs.get_func(a)
    out.write('\n===== %x size=%s =====\n'%(a,f.size() if f else '-'))
    try: out.write(str(ida_hexrays.decompile(a))[:90000])
    except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
