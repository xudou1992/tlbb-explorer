import idaapi, idc, ida_funcs, ida_hexrays, ida_name, ida_bytes
out = open(r"D:\TLGL\.scratch\ida\bip_dec_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
ea = 0x140643880
txt = str(ida_hexrays.decompile(ea))
w("len lines", len(txt.split("\n")))
w(txt[:14000])
w("\n== EsMesh vftable 0x140f09e10 ==")
for i in range(0, 100):
    p = ida_bytes.get_qword(0x140f09e10 + 8*i)
    if p == 0: break
    w(i, hex(p), ida_name.get_name(p) or "")
out.close()
idc.qexit(0)
