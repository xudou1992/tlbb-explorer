import idaapi, idc, ida_hexrays, ida_name
out = open(r"D:\TLGL\.scratch\ida\tailparse_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
for ea in (0x14073A190, 0x14073A940):
    w("\n########## %s %s ##########" % (hex(ea), ida_name.get_name(ea) or ""))
    try:
        w(str(ida_hexrays.decompile(ea))[:13000])
    except Exception as e:
        w("fail", repr(e))
out.close()
idc.qexit(0)
