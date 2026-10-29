# -*- coding: utf-8 -*-
"""对最短样本逐步打印 walker，并在假挂点头前回看 16B，验证是否为真 [1][N]+128B。"""
import os
import sys

sys.path.insert(0, r"D:\TLGL\.scratch\wave20\txnot")
import common as C
import json

OUT = r"D:\TLGL\.scratch\wave20\txnot"


def hexline(b, at, n=16):
    chunk = b[at:at + n]
    hx = " ".join("%02x" % c for c in chunk)
    asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
    return "%05x  %-47s  |%s|" % (at, hx, asc)


def walk_trace(b, start, vc):
    pos = start
    nodes = []
    log = []
    while pos < len(b):
        got = C.try_entry(b, pos, vc)
        if got is not None:
            nd, np = got
            log.append("ENTRY %s x=%d children=%s  0x%x->0x%x" % (
                nd["name"], nd["x"] if nd["x"] < 10 else nd["x"], nd["children"], pos, np))
            nodes.append(nd)
            pos = np
            continue
        if C.looks_record96(b, pos) is not None:
            nm = C.looks_record96(b, pos)[0]
            log.append("REC96 %s  0x%x->0x%x" % (nm, pos, pos + 96))
            pos += 96
            continue
        p0 = pos
        p = C.skip_blocks(b, pos, vc)
        if p != pos:
            log.append("SKIP_BLOCKS 0x%x->0x%x" % (pos, p))
        tx = C.try_tx(b, pos, vc)
        if tx is not None:
            log.append("TX flag=%d count=%d at=0x%x end=0x%x socks=%s left=%d" % (
                tx[0], tx[1], tx[3], tx[2], tx[4], len(b) - tx[2]))
            return nodes, tx, log
        u = C.u32(b, pos) if pos + 4 <= len(b) else -1
        log.append("STUCK @0x%x u32=%d" % (pos, u))
        return nodes, None, log
    log.append("ran off end")
    return nodes, None, log


def peek_before(b, tx_at, n=32):
    at = max(0, tx_at - n)
    lines = []
    while at < min(len(b), tx_at + 16):
        nm = C.name_at(b, at)
        extra = ""
        if nm:
            extra = " NAME='%s'" % nm
        if at + 4 <= len(b) and at % 4 == 0:
            extra += " u32=%d f32=%.5g" % (C.u32(b, at), C.f32(b, at))
        mark = " <<<" if at == tx_at else ""
        lines.append(hexline(b, at, min(16, len(b) - at)) + extra + mark)
        at += 16
    return lines


def true_socket_from_false(b, tx_at, tx_end):
    """假头在名字第 5–8 字节：真头 = tx_at-12，N=(EOF-(tx_at-12)-8)/128。"""
    true = tx_at - 12
    if true < 0 or true + 8 > len(b):
        return None
    flag = C.u32(b, true)
    cnt = C.u32(b, true + 4)
    end = true + 8 + 128 * cnt
    ok_eof = end == len(b)
    socks = []
    p = true + 8
    good = flag == 1 and 0 <= cnt <= 4096 and end <= len(b)
    if good:
        for _ in range(cnt):
            n1 = C.name_at(b, p)
            n2 = C.name_at(b, p + 32)
            if n1 is None or n2 is None:
                good = False
                break
            m = __import__("struct").unpack_from("<16f", b, p + 64)
            if abs(m[15] - 1.0) > 1e-3:
                good = False
                break
            socks.append((n1, n2))
            p += 128
    return {
        "true": true, "flag": flag, "count": cnt, "end": end,
        "eof": ok_eof, "parse_ok": good, "socks": socks,
        "left_formula": 128 * cnt - 12 if cnt else None,
    }


def main():
    rows = json.load(open(os.path.join(OUT, "txnot.json"), encoding="utf-8"))["rows"]
    lines = []
    w = lines.append

    # 最短 5 份逐步
    for r in rows[:5]:
        b = open(r["file"], "rb").read()
        starts, roots = C.candidates(b)
        w("=" * 78)
        w("%s size=%d declared=%d vc=%d starts=%s roots=%s" % (
            r["base"], r["size"], r["declared"], r["vc"],
            ["0x%x" % s for s in starts], ["0x%x" % s for s in roots]))
        for s in starts + roots:
            nodes, tx, log = walk_trace(b, s, r["vc"])
            w("-- walk start 0x%x  nodes=%d" % (s, len(nodes)))
            for L in log:
                w("   %s" % L)
        w("-- 假挂点头前回看")
        for L in peek_before(b, r["tx_at"], 32):
            w("   %s" % L)
        ts = true_socket_from_false(b, r["tx_at"], r["tx_end"])
        w("-- 回看 12B 假设: %s" % ts)
        w("")

    # 全量：leftover == 128N-12 且回看 [1][N] 能解到 EOF
    hit = miss = []
    miss = []
    buckets = {"formula_and_parse": 0, "formula_only": 0, "parse_only": 0, "neither": 0,
               "nnodes_ne": 0}
    details = []
    for r in rows:
        b = open(r["file"], "rb").read()
        ts = true_socket_from_false(b, r["tx_at"], r["tx_end"])
        nmatch = r["nnodes"] == r["declared"]
        formula = (r["left"] + 12) % 128 == 0 and r["left"] >= 116
        n = (r["left"] + 12) // 128 if formula else None
        ok = ts and ts["parse_ok"] and ts["eof"] and ts["flag"] == 1
        if not nmatch:
            buckets["nnodes_ne"] += 1
        if ok and formula:
            buckets["formula_and_parse"] += 1
        elif formula:
            buckets["formula_only"] += 1
        elif ok:
            buckets["parse_only"] += 1
        else:
            buckets["neither"] += 1
        details.append((r, ts, formula, n, ok, nmatch))

    w("=" * 78)
    w("全量 141：%s" % buckets)
    w("nnodes==declared: %d" % sum(1 for *_, nmatch in details if nmatch))
    w("回看12B 解出 flag=1 且 EOF: %d" % sum(1 for r, ts, *rest in details if ts and ts["parse_ok"] and ts["eof"]))
    w("leftover=128N-12: %d" % sum(1 for r, ts, formula, n, ok, nmatch in details if formula))

    # count 直方（回看成功的）
    import collections
    cnts = collections.Counter()
    names0 = collections.Counter()
    for r, ts, formula, n, ok, nmatch in details:
        if ts and ts["parse_ok"] and ts["eof"]:
            cnts[ts["count"]] += 1
            if ts["socks"]:
                names0[ts["socks"][0][0]] += 1
    w("回看成功的 N 直方: %s" % cnts.most_common())
    w("回看成功的首挂点名 top: %s" % names0.most_common(15))

    w("")
    w("失败例（回看解不出或不到 EOF）：")
    nfail = 0
    for r, ts, formula, n, ok, nmatch in details:
        if ts and ts["parse_ok"] and ts["eof"]:
            continue
        nfail += 1
        w("  %s left=%d nnodes=%d/%d tx_at=0x%x flag_false=%s ts=%s" % (
            r["base"], r["left"], r["nnodes"], r["declared"], r["tx_at"],
            r["tx_flag"], ts))
    w("失败例数 %d" % nfail)

    open(os.path.join(OUT, "back12.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("written back12.txt  buckets", buckets, "nfail", nfail)


if __name__ == "__main__":
    main()
