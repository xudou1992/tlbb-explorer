import idc, idautils, ida_funcs, ida_hexrays
out=open(r'D:/TLGL/.scratch/ida/inputlayout_out.txt','w',encoding='utf-8')
names=[]
for ea,name in idautils.Names():
    if 'InputLayout' in name or 'inputlayout' in name.lower() or 'IASetVertexBuffers' in name or 'IASetInputLayout' in name:
        names.append((ea,name))
out.write('names: %s\n'%(' | '.join('%x %s'%x for x in names)))
# xrefs to any named import
for ea,name in names:
    out.write('\n== %x %s\n'%(ea,name))
    for x in idautils.XrefsTo(ea,0):
        f=ida_funcs.get_func(x.frm)
        out.write('  from %x func=%s\n'%(x.frm,hex(f.start_ea) if f else '-'))
# also search for the string "CreateInputLayout" in imports
for s in idautils.Strings():
    if 'InputLayout' in str(s):
        out.write('str %x %r\n'%(s.ea,str(s)))
out.close()
idc.qexit(0)
