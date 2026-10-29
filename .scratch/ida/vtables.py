import idc, idautils, ida_bytes, ida_funcs
out=open(r'D:/TLGL/.scratch/ida/vtables_out.txt','w',encoding='utf-8')
for n in idautils.Names():
    if 'ModelST' in n[1] or 'MeshModel' in n[1]:
        out.write('%x %s\n'%(n[0],n[1]))
out.close()
idc.qexit(0)
