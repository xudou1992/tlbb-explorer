import idaapi, idautils, idc, ida_funcs, ida_hexrays, ida_bytes, ida_name, re
out = open(r"D:\TLGL\.scratch\ida\mesh_readers_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
cands = [0x1405E6850, 0x1405E8360, 0x140724BF0, 0x1407263F0, 0x140782990, 0x1407836D0]
for ea in cands:
    f = ida_funcs.get_func(ea)
    w("\n########## %s size=%d ##########" % (hex(ea), (f.end_ea - f.start_ea) if f else -1))
    try:
        txt = str(ida_hexrays.decompile(ea))
    except Exception as e:
        w("decomp fail", repr(e)); continue
    # 函数签名
    w(txt.split("\n")[0])
    w("   callees:", ", ".join(sorted({ida_name.get_name(c) or hex(c) for c in [x.frm if hasattr(x,'frm') else 0 for x in []]})) if False else "")
    # 只打可疑行
    keys = ["0x8C", "140LL", "0x110", "272LL", "vertex", "Vertex", "bone", "Bone", "skin", "Skin", "mesh", "Mesh", "Copyright", "strncmp", "memcmp", "sub_140", "*("]
    lines = [l for l in txt.split("\n") if any(k in l for k in keys)]
    w("   total_lines=%d suspicious=%d" % (len(txt.split("\n")), len(lines)))
    for l in lines[:120]:
        w("   ", l.strip()[:200])
out.close()
idc.qexit(0)
