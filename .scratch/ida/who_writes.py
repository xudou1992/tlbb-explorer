import idaapi, idautils, idc, ida_funcs, ida_ua, ida_bytes, ida_name
out = open(r"D:\TLGL\.scratch\ida\who_writes_out.txt", "w", encoding="utf-8")
def w(*a): print(*a, file=out, flush=True)
funcs = [0x14070FB70, 0x14072F6F0, 0x140736070, 0x1407A6E40]
for fea in funcs:
    f = ida_funcs.get_func(fea)
    w("\n########## %s size=%d ##########" % (hex(fea), f.end_ea - f.start_ea))
    strs, calls = [], []
    ea = f.start_ea
    while ea < f.end_ea:
        ins = ida_ua.insn_t()
        if ida_ua.decode_insn(ins, ea) > 0:
            if ins.get_canon_mnem() in ("call", "jmp"):
                for op in ins.ops:
                    if op.type in (ida_ua.o_near, ida_ua.o_far):
                        t = ida_funcs.get_func(op.addr)
                        if t: calls.append(ida_name.get_name(t.start_ea) or hex(t.start_ea))
            for op in ins.ops:
                if op.type in (ida_ua.o_mem, ida_ua.o_imm, ida_ua.o_displ):
                    a = op.addr
                    if a and ida_bytes.is_loaded(a):
                        s = idc.get_strlit_contents(a, -1, idc.STRTYPE_C)
                        if s and 3 <= len(s) <= 90 and all(32 <= c < 127 for c in s):
                            strs.append((hex(a), s.decode('ascii', 'replace')))
        ea = ida_bytes.next_head(ea, f.end_ea)
    seen = set(); uniq = []
    for a, s in strs:
        if (a, s) not in seen:
            seen.add((a, s)); uniq.append((a, s))
    w("strings:", len(uniq))
    for a, s in uniq[:26]:
        w("   ", a, repr(s))
    cs = []
    for c in calls:
        if c not in cs: cs.append(c)
    w("calls:", len(cs), ", ".join(cs[:24]))
out.close()
idc.qexit(0)
