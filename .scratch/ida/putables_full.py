import idaapi, idc, ida_bytes
out = open(r"D:\TLGL\.scratch\ida\putables_full_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def s_at(v):
    try:
        s = idc.get_strlit_contents(v, -1, idc.STRTYPE_C)
        if s:
            t = s.decode('ascii','replace')
            if 2 <= len(t) <= 48 and all(32 <= ord(c) < 127 for c in t):
                return t
    except Exception: pass
    return None
def is_entry(ea):
    a = ida_bytes.get_qword(ea); b = ida_bytes.get_qword(ea+8); c = ida_bytes.get_qword(ea+16)
    return s_at(a) is not None and b < 0x10000 and c < 0x100000
starts = {}
for anchor in (0x141072cc8, 0x1410615a8, 0x141072008):
    p = anchor
    while is_entry(p - 24) and anchor - p < 24*400: p -= 24
    q = anchor
    while is_entry(q + 24) and q - anchor < 24*400: q += 24
    starts[p] = q
for p, q in starts.items():
    w("\n== table %s .. %s  (%d entries) ==" % (hex(p), hex(q), (q-p)//24 + 1))
    ea = p
    while ea <= q:
        a = ida_bytes.get_qword(ea); b = ida_bytes.get_qword(ea+8); c = ida_bytes.get_qword(ea+16)
        w("  %-34s A=%-4d B=%d" % (s_at(a), b, c))
        ea += 24
out.close()
idc.qexit(0)
