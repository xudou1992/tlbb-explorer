"""读 "mesh" 类型注册项的描述符：qword_1410AD918 指向的结构里哪些字段是函数指针。
（防御版：每一步都往 meshdesc.out 里写，出错也能看到卡在哪一格。）
"""
import ida_bytes, ida_funcs, idc, json

TEXT_LO, TEXT_HI = 0x140001000, 0x141000000
LOG = r"D:\TLGL\.scratch\ida\meshdesc.out"
out = []


def w(*a):
    out.append(" ".join(str(x) for x in a))


for g in ["qword_1410AD918", "qword_1410ABB38"]:
    ea = idc.get_name_ea_simple(g)
    w("==", g, "全局地址", hex(ea & 0xFFFFFFFFFFFFFFFF))
    if ea in (idc.BADADDR, 0xFFFFFFFFFFFFFFFF):
        w("   名字找不到")
        continue
    try:
        p = ida_bytes.get_qword(ea)
    except Exception as e:
        w("   读指针失败", repr(e))
        continue
    w("   描述符指针", hex(p))
    if not (TEXT_LO - 0x2000000 < p < TEXT_HI + 0x2000000):
        w("   指针不像有效地址，跳过")
        continue
    for i in range(16):
        try:
            v = ida_bytes.get_qword(p + 8 * i)
        except Exception as e:
            w(f"   +{i*8} 读失败", repr(e))
            continue
        note = ""
        if TEXT_LO <= v < TEXT_HI:
            f = ida_funcs.get_func(v)
            note = "函数 " + (idc.get_func_name(f.start_ea) if f else "?")
        elif v and v < 0x142000000:
            try:
                s = idc.get_strlit_contents(v, -1, 0)
            except Exception:
                s = None
            note = ("串 " + s.decode("utf-8", "replace")) if s else idc.get_name(v, 60)
        w(f"   +{i*8:<3}", hex(v), note)

with open(LOG, "w", encoding="utf-8") as fp:
    fp.write("\n".join(out))
print("\n".join(out)[:2500])
