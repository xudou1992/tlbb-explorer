import idc, ida_funcs, ida_hexrays, idautils
a=0x1409A82A0
f=ida_funcs.get_func(a)
out=open(r'D:/TLGL/.scratch/ida/shaderclass_out.txt','w',encoding='utf-8')
out.write('func %x size=%s\n'%(a,f.size() if f else '-'))
try: out.write(str(ida_hexrays.decompile(a))[:200000])
except Exception as e: out.write('FAIL %r\n'%e)
out.close()
idc.qexit(0)
