# -*- coding: utf-8 -*-
"""最短 5 份尾巴 hex（假挂点头 vs 真挂点头）+ 14 份 G 仍失败的卡点现场。"""
import json
import os
import struct
import sys

sys.path.insert(0, r"D:\TLGL\.scratch\wave20\txnot")
import common as C

OUT = r"D:\TLGL\.scratch\wave20\txnot"


def hline(b, at, n=16):
    chunk = b[at:at + n]
    hx = " ".join("%02x" % c for c in chunk)
    asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
    extra = ""
    if at + 4 <= len(b) and at % 4 == 0:
        u = C.u32(b, at)
        f = C.f32(b, at)
        extra = "  u32=%d" % u
        if 1e-6 < abs(f) < 1e6 and abs(f - u) > 1e-6:
            extra += " f32=%.6g" % f
    nm = C.name_at(b, at)
    if nm:
        extra += "  NAME='%s'" % nm
    return "%05x  %-47s  |%s|%s" % (at, hx, asc, extra)


def dump(b, a, z, lines):
    at = a
    while at < z:
        lines.append(hline(b, at, min(16, z - at)))
        at += 16


def main():
    v = json.load(open(os.path.join(OUT, "verify.json"), encoding="utf-8"))
    # first-attempt 128 from 名单
    names128 = []
    for line in open(os.path.join(OUT, "名单_first_attempt.txt"), encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        names128.append(line.split("\t")[0])

    # path map
    j = json.load(open(os.path.join(OUT, "txnot.json"), encoding="utf-8"))
    bybase = {r["base"]: r for r in j["rows"]}
    # also need paths for the 128 that might not be in any-tx json if first-attempt only
    # all 128 are in first-attempt which is subset of... wait first-attempt 128 vs any 141.
    # first-attempt files are all in the 141? first-attempt is subset of any-tx. Yes.

    lines = []
    w = lines.append
    w("# tx-not-eof 128 份（first-attempt 口径，与 hamigua_v2.txt 对齐）")
    w("# G_OK=114  G_FAIL=14")
    w("# basename")
    for n in names128:
        w(n)
    open(os.path.join(OUT, "名单.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")

    # shortest 5 hex
    short = names128[:5]
    H = []
    h = H.append
    for n in short:
        r = bybase[n]
        b = open(r["file"], "rb").read()
        false_at = r["tx_at"]
        true_at = None
        # scan back up to 64B for [1][N] that hits EOF
        for back in range(0, 96, 4):
            at = false_at - back
            if at < 0:
                break
            if at + 8 > len(b):
                continue
            if C.u32(b, at) != 1:
                continue
            cnt = C.u32(b, at + 4)
            if 0 <= cnt <= 64 and at + 8 + 128 * cnt == len(b):
                n1 = C.name_at(b, at + 8)
                if n1:
                    true_at = at
                    true_n = cnt
                    true_nm = n1
                    break
        h("=" * 78)
        h("file=%s  size=%d(0x%x)  declared=%d  vc=%d  path=%s" % (
            n, len(b), len(b), r["declared"], r["vc"], r["file"]))
        h("V2 假挂点头 @0x%x  flag=%s count=%s  （名字第 5–8 字节被当成 flag，count=0）" %
          (false_at, r["tx_flag"], r["tx_count"]))
        h("假挂点段之后的尾巴 [%d B]  从 0x%x 到 EOF 0x%x：" % (r["left"], r["tx_end"], len(b)))
        dump(b, r["tx_end"], len(b), H)
        h("")
        if true_at is not None:
            h("真挂点头 @0x%x  [u32 1][u32 %d] + %d×128B  名字='%s'  恰好 EOF（left=0）" %
              (true_at, true_n, true_n, true_nm))
            h("真头前回看 16B（88B 对角块尾，三颗 100.0）+ 真头 8B + 第一条 128B 前 48B：")
            dump(b, max(0, true_at - 16), min(len(b), true_at + 8 + 48), H)
            h("真挂点段之后到 EOF：%d B" % (len(b) - (true_at + 8 + 128 * true_n)))
        else:
            h("（此份回看未钉到真头，见 G_FAIL）")
        h("")
    open(os.path.join(OUT, "hex_shortest5.txt"), "w", encoding="utf-8").write("\n".join(H) + "\n")

    # 14 stuck peek
    S = []
    s = S.append
    fail = v["txnot_first_still"]
    for n in fail:
        # find path by walking? use tree search from ROOT
        path = None
        for dirpath, _, names in os.walk(C.ROOT):
            if n in names:
                path = os.path.join(dirpath, n)
                break
        if not path:
            s("MISSING %s" % n)
            continue
        b = open(path, "rb").read()
        rec = C.analyze(path)
        pos = rec.get("tx_at", 0)
        s("=" * 78)
        s("%s size=%d declared=%d nnodes=%s stuck_near=0x%x" %
          (n, len(b), rec.get("declared"), rec.get("nnodes"), pos))
        s("卡点附近 64B：")
        dump(b, max(0, pos - 16), min(len(b), pos + 48), S)
        s("")
    open(os.path.join(OUT, "stuck14.txt"), "w", encoding="utf-8").write("\n".join(S) + "\n")
    print("wrote 名单.txt hex_shortest5.txt stuck14.txt  n128=%d nfail=%d" %
          (len(names128), len(fail)))


if __name__ == "__main__":
    main()
