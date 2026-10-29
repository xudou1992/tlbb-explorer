import ida_ua, ida_funcs, idc, idautils
hits={}
lo=0x140001000; hi=0x140000000+0x1400000
for ea in idautils.Heads(lo,hi):
    ins=ida_ua.insn_t()
    if ida_ua.decode_insn(ins,ea)==0: continue
    offs=set()
    for op in ins.ops:
        if op.type==ida_ua.o_displ or op.type==ida_ua.o_mem:
            offs.add(op.addr & 0xFFFFFFFF)
    if 0x8C in offs or 0x90 in offs:
        f=ida_funcs.get_func(ea)
        if f:
            hits.setdefault(f.start_ea,set()).update(offs & {0x8C,0x90,0x94,0x110,0x114})
out=open(r'D:/TLGL/.scratch/ida/mesh_hdr_readers_out.txt','w',encoding='utf-8')
n=0
for f,offs in sorted(hits.items()):
    if 0x8C in offs and 0x90 in offs:
        out.write('%x size=%d offs=%s\n'%(f,ida_funcs.get_func(f).size(),','.join(hex(x) for x in sorted(offs))))
        n+=1
out.write('total %d\n'%n)
out.close()
idc.qexit(0)
