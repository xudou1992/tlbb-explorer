import io, re, idaapi, idc, ida_hexrays, ida_name, ida_funcs
cands = []
for line in io.open(r"D:\TLGL\.scratch\ida\scan_offsets_out.txt", encoding="utf-8"):
    m = re.match(r"(0x[0-9a-f]+) ", line)
    if m: cands.append(int(m.group(1), 16))
out = io.open(r"D:\TLGL\.scratch\ida\score64_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
w("cands", len(cands))
scored = []
for ea in cands:
    try:
        txt = str(ida_hexrays.decompile(ea))
    except Exception:
        continue
    score = 0
    keys = []
    for k, wt in [("96", 3), ("0x110", 3), ("272", 2), ("memcpy", 1), ("malloc", 1), ("name", 1), ("Copyright", 4), ("140", 2), ("0x8C", 3)]:
        c = txt.count(k)
        score += c * wt
        if c: keys.append(f"{k}:{c}")
    scored.append((score, ea, keys, txt))
scored.sort(reverse=True)
for score, ea, keys, txt in scored[:10]:
    w("\n### score=%d %s %s  [%s]" % (score, hex(ea), ida_name.get_name(ea) or "", " ".join(keys)))
    for l in txt.split("\n"):
        if any(k in l for k in ["Copyright", "0x110", "memcpy", "malloc", "96", "0x8C"]):
            w("   ", l.strip()[:170])
out.close()
idc.qexit(0)
