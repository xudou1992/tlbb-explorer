import idaapi, idc, ida_hexrays
out = open(r"D:\TLGL\.scratch\ida\use144_out.txt", "w", encoding="utf-8")
txt = str(ida_hexrays.decompile(0x1407372E0))
print(txt, file=out)
out.close()
idc.qexit(0)
