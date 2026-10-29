import idc, ida_funcs, ida_hexrays, idautils, ida_bytes
out=open(r'D:/TLGL/.scratch/ida/loader_trace_out.txt','w',encoding='utf-8')
root=0x140736070
f=ida_funcs.get_func(root)
out.write('===== root %x size=%s =====\n'%(root, f.size() if f else '-'))
try: out.write(str(ida_hexrays.decompile(root))[:120000])
except Exception as e: out.write('FAIL %r\n'%e)
callees=set()
for x in idautils.XrefsFrom(root,0):
    g=ida_funcs.get_func(x.to)
    if g and g.start_ea!=root: callees.add(g.start_ea)
out.write('\ncallees: %s\n'%(' '.join(hex(a) for a in sorted(callees))))
for a in sorted(callees):
    g=ida_funcs.get_func(a)
    if not g or g.size()>12000: continue
    out.write('\n\n===== callee %x size=%d =====\n'%(a,g.size()))
    try: out.write(str(ida_hexrays.decompile(a))[:70000])
    except Exception as e: out.write('FAIL %r\n'%e)
# xrefs to the attribute size table
out.write('\n\n===== xrefs to 0x140DCD140 =====\n')
for x in idautils.XrefsTo(0x140DCD140,0):
    g=ida_funcs.get_func(x.frm)
    out.write('%x from %x func=%s\n'%(x.frm,x.frm,hex(g.start_ea) if g else '-'))
out.close()
idc.qexit(0)
