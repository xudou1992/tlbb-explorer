import idaapi, idautils, idc, ida_funcs, ida_name
out = open(r"D:\TLGL\.scratch\ida\jbpu_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
def fn(ea):
    f = ida_funcs.get_func(ea)
    return (ida_name.get_name(f.start_ea) or hex(f.start_ea), f.end_ea - f.start_ea) if f else ("(nofunc)", 0)
# 字符串表里的 JBPU
hits = []
for s in idautils.Strings():
    t = str(s)
    if "JBPU" in t or t == "pu":
        hits.append((s.ea, t))
w("string hits:", len(hits))
for ea, t in hits[:10]:
    w(repr(t), hex(ea))
    for x in idautils.XrefsTo(ea):
        w("   <-", hex(x.frm), fn(x.frm), "type", x.type)
# 立即数形式：搜索 0x4255504A ('JBPU' little-endian)
w("\n== immediates 0x4255504A ==")
cnt = 0
for fb in idautils.Functions():
    f = ida_funcs.get_func(fb)
    if not f or (f.end_ea - f.start_ea) > 20000: continue
    ea = f.start_ea
    while ea < f.end_ea:
        d = idc.get_wide_dword(ea)
        if d == 0x4255504A:
            w(hex(ea), fn(ea))
            cnt += 1
            if cnt > 20: break
        ea += 4
    if cnt > 20: break
w("count", cnt)
out.close()
idc.qexit(0)
