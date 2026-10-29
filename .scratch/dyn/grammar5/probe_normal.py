"""看一个「正常文件（现有解析器已认记录）」上的语法 B 命中长什么样，
对比 5 份异常文件：命中条数分布 + 首条命中逐字段解码。只读。"""
import os, re, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scanall import field_name, b_flags, full_bit, a_record, RUN, TREE, FIVE

OUT = os.path.dirname(os.path.abspath(__file__))
rows = [l.split("\t") for l in open(os.path.join(OUT, "scanall.tsv"), encoding="utf-8").read().splitlines()[1:]]
L = []
hits = [r for r in rows if int(r[5] or 0) > 0]
five_in = [r for r in hits if os.path.basename(r[0]) in FIVE]
other = [r for r in hits if os.path.basename(r[0]) not in FIVE]
L.append(f"B 命中(>=1 条)的文件 = {len(hits)}  其中 5 份异常文件 = {len(five_in)}  其它 = {len(other)}")
cnt = sorted(int(r[5]) for r in other)
q = lambda a, p: a[min(int(len(a) * p), len(a) - 1)] if a else None
L.append(f"其它文件 B 命中条数: min={cnt[0]} p50={q(cnt,.5)} p90={q(cnt,.9)} max={cnt[-1]}")
witha = [r for r in other if int(r[4] or 0) > 0]
L.append(f"其它命中文件里，现有解析器也已认到记录的（A>0）= {len(witha)}；A=0 的 = {len(other)-len(witha)}")
# B 是否只是「碰巧撞上几条」？看命中数 / 声明骨数 的比
rat = sorted(int(r[5]) / max(int(r[3] or 0), 1) for r in other)
L.append(f"命中数/声明骨数 比值: min={rat[0]:.3f} p50={q(rat,.5):.3f} p90={q(rat,.9):.3f} max={rat[-1]:.3f}")
L.append("")
L.append("### 抽查 4 份「正常且 B 也命中」的文件，看它 B 命中的是真记录还是巧合")
for r in sorted(witha, key=lambda x: -int(x[5]))[:4]:
    p = r[0]
    raw = open(p, "rb").read()
    vc, bones = int(r[2]), int(r[3])
    L.append("-" * 96)
    L.append(f"{os.path.basename(p)}  A={r[4]} B={r[5]} 声明骨={bones} vc={vc} size={len(raw)}")
    got = []
    for m in RUN.finditer(raw):
        i = m.start()
        if i % 4:
            continue
        fg = b_flags(raw, i, vc, bones)
        if fg & full_bit() == full_bit():
            got.append((i, fg))
    L.append(f"  重新定位到的 B 记录 {len(got)} 条，前 3 条逐字段：")
    for i, fg in got[:3]:
        nm = field_name(raw, i).decode()
        ws = [struct.unpack_from("<f", raw, i + 64 + 16 * k)[0] for k in range(4)]
        tris = [struct.unpack_from("<3f", raw, i + 64 + 16 * k + 4) for k in range(4)]
        lens = [sum(x * x for x in v) ** .5 for v in tris]
        N = struct.unpack_from("<I", raw, i + 132)[0]
        ids = struct.unpack_from("<%dI" % N, raw, i + 136)
        wts = struct.unpack_from("<%df" % N, raw, i + 136 + 4 * N)
        L.append(f"    @{hex(i)} 名={nm!r} 双名={field_name(raw,i+32)==nm}")
        L.append(f"      w 槽={['%.2e' % x for x in ws]}  齐次位@+128={struct.unpack_from('<f',raw,i+128)[0]:.4f}")
        L.append(f"      四组三元组长度={['%.5f' % x for x in lens]}")
        L.append(f"      基向量组0={tuple(round(x,5) for x in tris[0])}")
        L.append(f"      N={N} 骨号前12={ids[:12]}  权重前6={tuple(round(w,4) for w in wts[:6])}")
        L.append(f"      该位置若按现有 A 判据？={a_record(raw,i)}  记录长度 228+8N={228+8*N} 下一条起点={hex(i+228+8*N)}")
        nxt = i + 228 + 8 * N
        L.append(f"      下一条位置 @+{228+8*N} 是否又是 B 记录={any(x==nxt for x,_ in got)}"
                 f"  是否 A 记录={a_record(raw,nxt)}")
        L.append(f"      该处原始 32 字节: {raw[i:i+32]!r}")
open(os.path.join(OUT, "probe_normal_b.txt"), "w", encoding="utf-8").write("\n".join(L))
print("\n".join(x.encode("unicode_escape").decode() for x in L[:8]))
