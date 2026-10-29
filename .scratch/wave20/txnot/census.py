# -*- coding: utf-8 -*-
"""圈出 V2 walker 的 tx-not-eof 族：名单、尾巴长度直方、最短 5 份 hex。"""
import collections
import json
import os
import struct
import sys

sys.path.insert(0, r"D:\TLGL\.scratch\wave20\txnot")
import common as C

OUT = r"D:\TLGL\.scratch\wave20\txnot"


def hexline(b, at, n=16):
    chunk = b[at:at + n]
    hx = " ".join("%02x" % c for c in chunk)
    asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
    return "%05x  %-47s  |%s|" % (at, hx, asc)


def annotate(b, at):
    notes = []
    if at + 4 <= len(b) and at % 4 == 0:
        u = C.u32(b, at)
        f = C.f32(b, at)
        if u < 100000 and abs(u - f) < 1e-6:
            notes.append("u32=%d" % u)
        elif 1e-6 < abs(f) < 1e5:
            notes.append("f32=%.6g" % f)
        elif u == 0xFFFFFFFF:
            notes.append("u32=-1")
        elif u < 100000:
            notes.append("u32=%d" % u)
        else:
            notes.append("u32=0x%08x" % u)
    nm = C.name_at(b, at)
    if nm:
        notes.append("NAME:'%s'" % nm)
    return "  ".join(notes)


def dump_range(b, start, end, lines, prefix=""):
    at = start
    while at < end:
        n = min(16, end - at)
        lines.append(prefix + hexline(b, at, n) + "  " + annotate(b, at))
        at += 16


def leftover_probe(b, at):
    """尾巴开头形态：不解释，只记账。"""
    left = len(b) - at
    names = []
    i = at
    while i + 32 <= len(b):
        nm = C.name_at(b, i)
        if nm:
            names.append((i - at, nm))
            i += 32
        else:
            i += 4
    u0 = C.u32(b, at) if at + 4 <= len(b) else None
    u1 = C.u32(b, at + 4) if at + 8 <= len(b) else None
    u2 = C.u32(b, at + 8) if at + 12 <= len(b) else None
    f0 = C.f32(b, at) if at + 4 <= len(b) else None
    return {
        "left": left,
        "u0": u0, "u1": u1, "u2": u2, "f0": f0,
        "names": names[:12],
        "mat64": C.looks_mat64(b, at),
        "u92": C.looks_u92(b, at),
        "inf": C.looks_inf(b, at, C.u32(b, 0x8C)) if len(b) >= 0x90 else False,
        "rec96": None if C.looks_record96(b, at) is None else C.looks_record96(b, at)[0],
        "head16": b[at:at + 16].hex(" "),
    }


def main():
    files = sorted(C.iter_declared_mesh())
    ok = []
    txnot = []
    other = []
    for i, p in enumerate(files):
        r = C.analyze(p)
        if r.get("ok"):
            ok.append(r)
        elif str(r.get("err", "")).startswith("tx-not-eof"):
            b = open(p, "rb").read()
            r["probe"] = leftover_probe(b, r["tx_end"])
            txnot.append(r)
        else:
            other.append(r)
        if (i + 1) % 400 == 0:
            print("... %d/%d ok=%d txnot=%d other=%d" % (
                i + 1, len(files), len(ok), len(txnot), len(other)), flush=True)

    lines = []
    w = lines.append
    w("declared>0 = %d  V2走通 = %d  tx-not-eof = %d  其它失败 = %d" %
      (len(files), len(ok), len(txnot), len(other)))
    oerr = collections.Counter(r.get("err", "?")[:60] for r in other)
    w("其它失败聚类 top10：%s" % oerr.most_common(10))
    w("")

    lefts = collections.Counter(r["left"] for r in txnot)
    w("尾巴字节数直方（全部 %d 份）：" % len(txnot))
    for k, c in lefts.most_common():
        w("  %5d B × %d" % (k, c))
    flags = collections.Counter((r.get("tx_flag"), r.get("tx_count")) for r in txnot)
    w("挂点段 (flag,count) 直方：%s" % flags.most_common())
    nmatch = sum(1 for r in txnot if r.get("nnodes") == r.get("declared"))
    w("条目数==声明数（tree 未验，仅 walk 条数）：%d / %d" % (nmatch, len(txnot)))
    w("flag==1：%d / %d" % (sum(1 for r in txnot if r.get("tx_flag") == 1), len(txnot)))

    u0s = collections.Counter(r["probe"]["u0"] for r in txnot)
    w("尾巴首 u32 直方 top12：%s" % u0s.most_common(12))
    u1s = collections.Counter(r["probe"]["u1"] for r in txnot)
    w("尾巴次 u32 直方 top12：%s" % u1s.most_common(12))
    nnames = collections.Counter(len(r["probe"]["names"]) for r in txnot)
    w("尾巴内名字槽个数直方：%s" % nnames.most_common())
    firstnames = collections.Counter(
        r["probe"]["names"][0][1] if r["probe"]["names"] else "-" for r in txnot)
    w("尾巴第一个名字 top12：%s" % firstnames.most_common(12))
    shape = collections.Counter()
    for r in txnot:
        p = r["probe"]
        keys = []
        if p["mat64"]:
            keys.append("mat64")
        if p["u92"]:
            keys.append("u92")
        if p["inf"]:
            keys.append("inf")
        if p["rec96"]:
            keys.append("rec96:%s" % p["rec96"])
        if p["names"]:
            keys.append("names")
        shape[tuple(keys) or ("raw",)] += 1
    w("尾巴开头形态：%s" % shape.most_common())
    w("")

    # 名单
    txnot.sort(key=lambda r: (r["size"], os.path.basename(r["file"])))
    list_lines = []
    list_lines.append("# tx-not-eof 名单  %d 份  按文件字节数升序" % len(txnot))
    list_lines.append("# basename  size  declared  vc  tx_flag  tx_count  tx_at  tx_end  leftover  nnodes  socks")
    for r in txnot:
        socks = ",".join("%s->%s" % (a, b) for a, b in r.get("socks") or [])
        list_lines.append("%s\t%d\t%d\t%d\t%d\t%d\t0x%x\t0x%x\t%d\t%d\t%s" % (
            os.path.basename(r["file"]), r["size"], r["declared"], r["vc"],
            r.get("tx_flag", -1), r.get("tx_count", -1),
            r.get("tx_at", 0), r.get("tx_end", 0), r.get("left", -1),
            r.get("nnodes", -1), socks))
    open(os.path.join(OUT, "名单.txt"), "w", encoding="utf-8").write("\n".join(list_lines) + "\n")

    w("最短 5 份：")
    hex_lines = []
    for r in txnot[:5]:
        p = r["file"]
        b = open(p, "rb").read()
        w("  %s size=%d declared=%d vc=%d nnodes=%d tx=(%s,%s)@0x%x..0x%x left=%d socks=%s" % (
            os.path.basename(p), r["size"], r["declared"], r["vc"], r["nnodes"],
            r.get("tx_flag"), r.get("tx_count"), r.get("tx_at", 0), r.get("tx_end", 0),
            r["left"], r.get("socks")))
        hex_lines.append("=" * 78)
        hex_lines.append("file=%s size=%d(0x%x) declared=%d vc=%d nnodes=%d" % (
            os.path.basename(p), len(b), len(b), r["declared"], r["vc"], r["nnodes"]))
        hex_lines.append("挂点段 [u32 flag=%d][u32 count=%d] @0x%x  记录起 0x%x  记录止 0x%x  EOF=0x%x  left=%d" % (
            r["tx_flag"], r["tx_count"], r["tx_at"], r["tx_at"] + 8, r["tx_end"], len(b), r["left"]))
        hex_lines.append("socks: %s" % r.get("socks"))
        # 挂点段头 8B + 每条名字（已知段只标位置，不重解）
        hex_lines.append("-- 挂点段头 8B（已知，只标位置）")
        dump_range(b, r["tx_at"], r["tx_at"] + 8, hex_lines)
        hex_lines.append("-- 挂点段之后的尾巴 [0x%x, EOF)  %d B" % (r["tx_end"], r["left"]))
        dump_range(b, r["tx_end"], len(b), hex_lines)
        hex_lines.append("")
        # 尾巴按 u32/f32 一行 4 槽
        hex_lines.append("-- 尾巴 u32/f32 槽表")
        at = r["tx_end"]
        while at + 4 <= len(b):
            u = C.u32(b, at)
            f = C.f32(b, at)
            nm = C.name_at(b, at)
            extra = ""
            if nm:
                extra = "  NAME='%s'" % nm
            hex_lines.append("  0x%05x  u32=%10d  f32=%14.6g  hex=%s%s" % (
                at, u, f, b[at:at + 4].hex(" "), extra))
            at += 4
        hex_lines.append("")

    open(os.path.join(OUT, "census.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    open(os.path.join(OUT, "hex_shortest5.txt"), "w", encoding="utf-8").write("\n".join(hex_lines) + "\n")

    slim = []
    for r in txnot:
        slim.append({
            "file": r["file"], "base": os.path.basename(r["file"]),
            "size": r["size"], "declared": r["declared"], "vc": r["vc"],
            "nnodes": r["nnodes"], "tx_flag": r.get("tx_flag"),
            "tx_count": r.get("tx_count"), "tx_at": r.get("tx_at"),
            "tx_end": r.get("tx_end"), "left": r.get("left"),
            "socks": r.get("socks"), "probe": r["probe"],
        })
    with open(os.path.join(OUT, "txnot.json"), "w", encoding="utf-8") as f:
        json.dump({"ok": len(ok), "txnot": len(txnot), "other": len(other),
                   "ok_files": [os.path.basename(x["file"]) for x in ok],
                   "rows": slim}, f, ensure_ascii=False, indent=0)

    # 成功样本名单，后面零回退要用
    open(os.path.join(OUT, "v2_ok.txt"), "w", encoding="utf-8").write(
        "\n".join(x["file"] for x in ok) + "\n")
    print("written census: ok=%d txnot=%d other=%d" % (len(ok), len(txnot), len(other)))


if __name__ == "__main__":
    main()
