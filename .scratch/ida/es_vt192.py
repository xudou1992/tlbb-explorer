import idc, ida_bytes, ida_funcs, ida_hexrays
out=open(r'D:/TLGL/.scratch/ida/es_vt192_out.txt','w',encoding='utf-8')
va=0x140f0e0a8
for off in [184,192,200,208,224,240]:
    q=ida_bytes.get_qword(va+off)
    out.write('\n== +%d -> %x\n'%(off,q))
    f=ida_funcs.get_func(q)
    if f: out.write('func=%x size=%s\n'%(f.start_ea,f.size()))
    try: out.write(str(ida_hexrays.decompile(q))[:60000])
    except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
