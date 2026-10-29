import idaapi, idc, ida_bytes
out = open(r"D:\TLGL\.scratch\ida\putable_tail_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def s_at(v):
    try:
        s = idc.get_strlit_contents(v, -1, idc.STRTYPE_C)
        if s:
            t = s.decode('ascii','replace')
            if 2 <= len(t) <= 48: return t
    except Exception: pass
    return None
start = 0x141074588 + 24
ea = start
for k in range(0, 80):
    a = ida_bytes.get_qword(ea); b = ida_bytes.get_qword(ea+8); c = ida_bytes.get_qword(ea+16)
    if a == 0 and b == 0 and c == 0:
        w("%s  (zero entry) — 停" % hex(ea)); break
    w("%s  %-40s A=%s B=%s" % (hex(ea), repr(s_at(a)), b, c))
    ea += 24
out.close()
idc.qexit(0)
