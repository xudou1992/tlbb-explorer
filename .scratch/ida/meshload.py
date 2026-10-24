import idaapi, idc, ida_hexrays, ida_funcs, ida_name
out = open(r"D:\TLGL\.scratch\ida\meshload_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
w(str(ida_hexrays.decompile(0x140736070)))
w("\n== callees ==")
import idautils
f = ida_funcs.get_func(0x140736070)
for ea in idautils.FuncItems(f.start_ea):
    ins = idaapi.insn_t()
    if idaapi.decode_insn(ins, ea) > 0 and ins.get_canon_mnem() == "call":
        t = ins.ops[0].addr
        g = ida_funcs.get_func(t)
        if g: w(hex(g.start_ea), ida_name.get_name(g.start_ea) or "", "size", g.end_ea - g.start_ea)
out.close()
idc.qexit(0)
