import idc, ida_bytes, ida_funcs, ida_hexrays, idautils, ida_ua
out=open(r'D:/TLGL/.scratch/ida/es_texture2_out.txt','w',encoding='utf-8')
out.write('names with Texture:\n')
for ea,name in idautils.Names():
    if 'Texture' in name or 'texture' in name:
        out.write('  %x %s\n'%(ea,name))
out.write('\ndisasm constructor 1406C77B0:\n')
ea=0x1406C77B0
for i in range(0,60):
    line=idc.generate_disasm_line(ea,0)
    out.write('  %x %s\n'%(ea,line))
    ea += idc.get_item_size(ea)
out.close()
idc.qexit(0)
