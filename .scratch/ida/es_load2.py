import idc, ida_bytes, ida_funcs, ida_hexrays
out=open(r'D:/TLGL/.scratch/ida/es_load2_out.txt','w',encoding='utf-8')
v1=idc.get_operand_value(0x1406C77CB,1)
v2=idc.get_operand_value(0x1406C77DF,1)
out.write('v1=%x v2=%x\n'%(v1,v2))
for tag,va in [('v1',v1),('v2',v2)]:
    out.write('\n== %s %x\n'%(tag,va))
    for i in range(0,20):
        q=ida_bytes.get_qword(va+i*8)
        if q and 0x140000000<=q<0x141400000:
            f=ida_funcs.get_func(q)
            out.write('  +%d %x func=%s size=%s\n'%(i*8,q,hex(f.start_ea) if f else '-',f.size() if f else '-'))
    fn=ida_bytes.get_qword(va+96)
    out.write('-- +96 -> %x\n'%fn)
    try: out.write(str(ida_hexrays.decompile(fn))[:120000])
    except Exception as e: out.write('FAIL %r\n'%e)
# real load helper
for a in [0x1406C53C0]:
    out.write('\n\n===== %x =====\n'%a)
    try: out.write(str(ida_hexrays.decompile(a))[:120000])
    except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
