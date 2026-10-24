import idaapi, idc, ida_hexrays, ida_name
out = open(r"D:\TLGL\.scratch\ida\reg2_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
for ea in (0x140900280, 0x140C82350, 0x1408FE060, 0x140C822F0):
    w("\n########## %s %s ##########" % (hex(ea), ida_name.get_name(ea) or ""))
    try:
        w(str(ida_hexrays.decompile(ea))[:5000])
    except Exception as e:
        w("fail", repr(e))
out.close()
idc.qexit(0)
