import idaapi, idc, ida_hexrays
out = open(r"D:\TLGL\.scratch\ida\pu_reader_out.txt", "w", encoding="utf-8")
try:
    txt = str(ida_hexrays.decompile(0x140798450))
    print(txt[:60000], file=out)
except Exception as e:
    print("fail", repr(e), file=out)
out.close()
idc.qexit(0)
