import idaapi, idc, ida_hexrays, ida_name
out = open(r"D:\TLGL\.scratch\ida\two2_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
for ea in (0x1407A1880, 0x1407AA7A0):
    w("\n########## %s %s ##########" % (hex(ea), ida_name.get_name(ea) or ""))
    try:
        w(str(ida_hexrays.decompile(ea))[:9000])
    except Exception as e:
        w("fail", repr(e))
out.close()
idc.qexit(0)
