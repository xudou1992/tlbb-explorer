import idaapi, idc, ida_hexrays, ida_bytes, idc as _i
out = open(r"D:\TLGL\.scratch\ida\two_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
# 先看那个 3 字符常量是什么
try:
    b = ida_bytes.get_bytes(0x140EF5D40, 8) or b""
    w("unk_140EF5D40:", b)
except Exception as e:
    w("bytes fail", repr(e))
for ea in (0x14065AE60, 0x1407AA7A0):
    w("\n########## %s ##########" % hex(ea))
    try:
        w(str(ida_hexrays.decompile(ea))[:12000])
    except Exception as e:
        w("fail", repr(e))
out.close()
idc.qexit(0)
