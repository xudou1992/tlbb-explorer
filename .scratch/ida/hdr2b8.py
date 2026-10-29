import ida_ua, ida_funcs, idc, idautils
hits={}
lo=0x140001000; hi=0x140c8b000
for ea in idautils.Heads(lo,hi):
    ins=ida_ua.insn_t()
    if ida_ua.decode_insn(ins,ea)==0: continue
    offs=set()
    for op in ins.ops:
        if op.type in (ida_ua.o_displ, ida_ua.o_mem):
            offs.add(op.addr & 0xFFFFFFFF)
    if 0x2B8 in offs:
        f=ida_funcs.get_func(ea)
        if f: hits.setdefault(f.start_ea,set()).update(offs)
out=open(r'D:/TLGL/.scratch/ida/hdr2b8_out.txt','w',encoding='utf-8')
for f,offs in sorted(hits.items()):
    if 0x8C in offs and 0x90 in offs:
        out.write('%x size=%d offs=%s\n'%(f,ida_funcs.get_func(f).size(),','.join(hex(x) for x in sorted(offs))))
out.close()
idc.qexit(0)
