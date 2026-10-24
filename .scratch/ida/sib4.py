import idaapi, idc, ida_hexrays, ida_name
out = open(r"D:\TLGL\.scratch\ida\sib4_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
for ea in [0x1405C3DC0, 0x1405FE5F0, 0x1406001D0, 0x14062BFC0]:
    w("\n########## %s %s ##########" % (hex(ea), ida_name.get_name(ea) or ""))
    try:
        txt = str(ida_hexrays.decompile(ea))
    except Exception as e:
        w("fail", repr(e)); continue
    lines = txt.split("\n")
    w("lines", len(lines))
    hit = 0
    for i, l in enumerate(lines):
        if any(k in l for k in ["140", "0x8C", "96", " 32)", "32u", "bone", "Bone", "skin", "Skin", "Copyright"]):
            w("   ", l.strip()[:190]); hit += 1
            if hit > 45: break
out.close()
idc.qexit(0)
