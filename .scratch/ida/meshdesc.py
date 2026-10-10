"""读 "mesh" 类型注册项的描述符：qword_1410AD918 指向的结构里每个字段是什么。
若某字段是 .text 里的函数指针，顺着反编译就是网格装载器。
"""
import ida_bytes, ida_funcs, idc, json

TEXT_LO, TEXT_HI = 0x140001000, 0x141000000
out = []
for g in ["qword_1410AD918", "qword_1410ABB38"]:
    ea = idc.get_name_ea_simple(g)
    p = ida_bytes.get_qword(ea)
    rows = []
    for i in range(12):
        v = ida_bytes.get_qword(p + 8 * i) if p else 0
        note = ""
        if TEXT_LO <= v < TEXT_HI:
            f = ida_funcs.get_func(v)
            note = "函数 " + (idc.get_func_name(f.start_ea) if f else "?")
        elif v and v < 0x142000000:
            s = idc.get_strlit_contents(v, -1, 0)
            note = ("串 " + s.decode("utf-8", "replace")) if s else idc.get_name(v, 60)
        rows.append((i * 8, hex(v), note))
    out.append((g, hex(ea), hex(p), rows))
with open(r"D:\TLGL\.scratch\ida\meshdesc.out", "w", encoding="utf-8") as fp:
    json.dump(out, fp, ensure_ascii=False, indent=1)
for g, ea, p, rows in out:
    print("==", g, ea, "->", p)
    for off, v, note in rows:
        print(f"   +{off:<3} {v:>18}  {note}")
