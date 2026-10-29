import idaapi, idautils, idc, ida_funcs, ida_bytes, ida_ua, ida_name
out = open(r"D:\TLGL\.scratch\ida\skelptr_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
hits = []
for fea in idautils.Functions():
    f = ida_funcs.get_func(fea)
    if not f or (f.end_ea - f.start_ea) > 20000: continue
    ea = f.start_ea
    while ea < f.end_ea:
        ins = ida_ua.insn_t()
        if ida_ua.decode_insn(ins, ea) > 0:
            for op in ins.ops:
                if op.type in (ida_ua.o_displ, ida_ua.o_mem) and op.addr == 0x288:
                    hits.append((f.start_ea, f.end_ea - f.start_ea))
                    ea = f.end_ea
                    break
        ea = ida_bytes.next_head(ea, f.end_ea)
w("funcs with disp 0x288:", len(hits))
for ea, sz in hits[:40]:
    w(hex(ea), ida_name.get_name(ea) or "", "size", sz)
out.close()
idc.qexit(0)
