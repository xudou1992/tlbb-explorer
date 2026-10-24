import idaapi, idautils, idc, ida_funcs, ida_bytes, ida_ua, ida_name
out = open(r"D:\TLGL\.scratch\ida\vec96_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
hits = []
for fea in idautils.Functions():
    f = ida_funcs.get_func(fea)
    if not f or (f.end_ea - f.start_ea) > 12000: continue
    has = {0x178: False, 0x180: False, 0x448: False, 0x450: False}
    ea = f.start_ea
    while ea < f.end_ea:
        ins = ida_ua.insn_t()
        if ida_ua.decode_insn(ins, ea) > 0:
            for op in ins.ops:
                if op.type in (ida_ua.o_displ, ida_ua.o_mem) and op.addr in has:
                    has[op.addr] = True
        ea = ida_bytes.next_head(ea, f.end_ea)
    if has[0x178] and has[0x180]:
        hits.append((f.start_ea, f.end_ea - f.start_ea, has[0x448], has[0x450]))
w("hits(0x178+0x180):", len(hits))
for ea, sz, a, b in hits[:40]:
    w(hex(ea), ida_name.get_name(ea) or "", "size", sz, "has448", a, "has450", b)
out.close()
idc.qexit(0)
