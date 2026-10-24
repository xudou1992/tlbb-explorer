import idaapi, idc, ida_funcs, ida_hexrays, ida_name
out = open(r"D:\TLGL\.scratch\ida\dec3_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
for ea in [0x1404A58E0, 0x1401F50C0, 0x14035C0B0, 0x140519F90]:
    w("\n########## %s %s ##########" % (hex(ea), ida_name.get_name(ea) or ""))
    try:
        txt = str(ida_hexrays.decompile(ea))
    except Exception as e:
        w("decomp fail", repr(e)); continue
    w(txt[:9000])
out.close()
idc.qexit(0)
