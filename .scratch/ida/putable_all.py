import idaapi, idc, ida_bytes
out = open(r"D:\TLGL\.scratch\ida\putable_all_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def s_at(v):
    try:
        s = idc.get_strlit_contents(v, -1, idc.STRTYPE_C)
        if s:
            t = s.decode('ascii','replace')
            if 2 <= len(t) <= 48: return t
    except Exception: pass
    return None
ea = 0x141071ea0
n = 0
while n < 900:
    a = ida_bytes.get_qword(ea); b = ida_bytes.get_qword(ea+8); c = ida_bytes.get_qword(ea+16)
    name = s_at(a)
    if a == 0 and b == 0 and c == 0:
        w("STOP zero at %s (entries %d)" % (hex(ea), n)); break
    if name is None:
        w("STOP unreadable at %s (entries %d) a=%s b=%s c=%s" % (hex(ea), n, hex(a), b, c)); break
    w("%d\t%s\t%d" % (c, name, b))
    n += 1
    ea += 24
out.close()
idc.qexit(0)
