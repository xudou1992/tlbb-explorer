import idaapi, idautils, idc, ida_funcs, ida_bytes, ida_ua, ida_name
out = open(r"D:\TLGL\.scratch\ida\bone448_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
hits = []
for fea in idautils.Functions():
    f = ida_funcs.get_func(fea)
    if not f or (f.end_ea - f.start_ea) > 20000: continue
    has448 = False; has90 = False
    ea = f.start_ea
    while ea < f.end_ea:
        ins = ida_ua.insn_t()
        if ida_ua.decode_insn(ins, ea) > 0:
            for op in ins.ops:
                if op.type in (ida_ua.o_displ, ida_ua.o_mem):
                    if op.addr == 0x1C0: has448 = True
                    elif op.addr == 0x90: has90 = True
        ea = ida_bytes.next_head(ea, f.end_ea)
    if has448:
        hits.append((f.start_ea, f.end_ea - f.start_ea, has90))
w("funcs with disp 0x1C0:", len(hits))
for ea, sz, h90 in hits[:40]:
    w(hex(ea), ida_name.get_name(ea) or "", "size", sz, "has90", h90)
out.close()
idc.qexit(0)
