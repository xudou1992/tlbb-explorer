import idaapi, idautils, idc, ida_funcs, ida_bytes, ida_name, ida_ua
out = open(r"D:\TLGL\.scratch\ida\scan_offsets_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
hits = []
nfun = 0
for fea in idautils.Functions():
    f = ida_funcs.get_func(fea)
    if not f: continue
    size = f.end_ea - f.start_ea
    if size > 6000: continue
    nfun += 1
    has8c = has110 = False
    ea = f.start_ea
    while ea < f.end_ea:
        ins = ida_ua.insn_t()
        if ida_ua.decode_insn(ins, ea) > 0:
            for op in ins.ops:
                if op.type in (ida_ua.o_displ, ida_ua.o_mem):
                    if op.addr == 0x8C: has8c = True
                    elif op.addr == 0x110: has110 = True
            if has8c and has110:
                hits.append((f.start_ea, size))
                break
        ea = ida_bytes.next_head(ea, f.end_ea)
    if nfun % 5000 == 0:
        w("progress", nfun, "hits", len(hits))
w("scanned funcs", nfun, "hits", len(hits))
for ea, size in hits[:80]:
    w(hex(ea), ida_name.get_name(ea), "size", size)
out.close()
idc.qexit(0)
