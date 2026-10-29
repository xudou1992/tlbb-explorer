# -*- coding: utf-8 -*-
"""文法 G：条目之后的块链上，每个偏移先试挂点段
  [u32 1][u32 N][N × 128B] 且 end==EOF
再才跳 u92/mat64/inf。禁止把 [u32 1] 当 inf N=1。

验证：
  1. 复现 tx-not-eof 集合（first-attempt 口径 vs 任一起点口径）
  2. G 让该集合走到 EOF 的份数
  3. V2 已走通的 2208 份零回退
"""
import collections
import json
import os
import struct
import sys

sys.path.insert(0, r"D:\TLGL\.scratch\wave20\txnot")
import common as C

OUT = r"D:\TLGL\.scratch\wave20\txnot"


def sockets_at(b, at):
    """Rust tail_sockets_at：flag==1 且 8+128N == EOF。"""
    if at + 8 > len(b):
        return None
    if C.u32(b, at) != 1:
        return None
    cnt = C.u32(b, at + 4)
    if cnt > 4096:
        return None
    end = at + 8 + 128 * cnt
    if end != len(b):
        return None
    socks = []
    p = at + 8
    for _ in range(cnt):
        n1 = C.name_at(b, p)
        n2 = C.name_at(b, p + 32)
        if n1 is None or n2 is None:
            return None
        m = struct.unpack_from("<16f", b, p + 64)
        if abs(m[15] - 1.0) > 1e-3:
            return None
        if not all(abs(v) < 1e7 for v in m):
            return None
        socks.append((n1, n2, m))
        p += 128
    return {"flag": 1, "count": cnt, "at": at, "end": p, "socks": socks}


def try_tx_G(b, pos, vc):
    """块链逐点先试 sockets_at，失败再跳一块。"""
    p = pos
    while True:
        got = sockets_at(b, p)
        if got is not None:
            return got
        if C.looks_u92(b, p):
            p += 88
            continue
        if C.looks_mat64(b, p):
            p += 64
            continue
        if C.looks_inf(b, p, vc):
            p += 4 + 8 * C.u32(b, p)
            continue
        return None


def walk_G(b, start, vc):
    pos = start
    nodes = []
    while pos < len(b):
        got = C.try_entry(b, pos, vc)
        if got is not None:
            nd, pos = got
            nodes.append(nd)
            continue
        if C.looks_record96(b, pos) is not None:
            pos += 96
            continue
        tx = try_tx_G(b, pos, vc)
        if tx is not None:
            return nodes, tx, None
        return nodes, None, "stuck@0x%x" % pos
    return nodes, None, "not-eof"


def analyze_both(path):
    b = open(path, "rb").read()
    if len(b) < 0x114:
        return None
    declared = C.u32(b, 0x110)
    vc = C.u32(b, 0x8C)
    if not (0 < declared <= 4096):
        return None
    starts, roots = C.candidates(b)
    old_ok = None
    old_fail = []
    new_ok = None
    new_fail = []
    for start in starts + roots:
        nodes, tx, pos, err = C.walk_tail(b, start, vc)
        if not err:
            bad = C.tree_check(nodes, declared)
            if not bad:
                old_ok = {"start": start, "tx_count": tx[1], "kind":
                          "origin" if start in starts else "root-flag"}
                break
            old_fail.append((start, bad, len(nodes)))
        else:
            old_fail.append((start, err, len(nodes), tx, pos))
    for start in starts + roots:
        nodes, tx, err = walk_G(b, start, vc)
        if not err:
            bad = C.tree_check(nodes, declared)
            if not bad:
                new_ok = {
                    "start": start,
                    "kind": "origin" if start in starts else "root-flag",
                    "tx_count": tx["count"], "tx_at": tx["at"],
                    "socks": [(a, b_) for a, b_, _ in tx["socks"]],
                    "nnodes": len(nodes),
                }
                break
            new_fail.append((start, bad, len(nodes)))
        else:
            new_fail.append((start, err, len(nodes)))
    return {
        "file": path, "base": os.path.basename(path),
        "declared": declared, "vc": vc, "size": len(b),
        "old_ok": old_ok, "old_fail": old_fail,
        "new_ok": new_ok, "new_fail": new_fail,
    }


def first_err(fails):
    if not fails:
        return "no-candidate"
    e = fails[0][1]
    if e.startswith("tx-not-eof"):
        return "tx-not-eof"
    if e.startswith("stuck"):
        return "stuck"
    if e.startswith("roots"):
        return "roots"
    if e.startswith("child-listed-twice"):
        return "child-listed-twice"
    if e.startswith("count "):
        return "count"
    return e[:40]


def main():
    files = sorted(C.iter_declared_mesh())
    rows = []
    for i, p in enumerate(files):
        r = analyze_both(p)
        rows.append(r)
        if (i + 1) % 400 == 0:
            print("... %d/%d" % (i + 1, len(files)), flush=True)

    old_ok = [r for r in rows if r["old_ok"]]
    new_ok = [r for r in rows if r["new_ok"]]
    old_tx = [r for r in rows if not r["old_ok"] and first_err(r["old_fail"]) == "tx-not-eof"]
    any_tx = [r for r in rows if not r["old_ok"] and any(
        str(x[1]).startswith("tx-not-eof") for x in r["old_fail"])]

    regress = [r for r in rows if r["old_ok"] and not r["new_ok"]]
    gained = [r for r in old_tx if r["new_ok"]]
    still = [r for r in old_tx if not r["new_ok"]]
    gained_any = [r for r in any_tx if r["new_ok"]]
    still_any = [r for r in any_tx if not r["new_ok"]]

    lines = []
    w = lines.append
    w("declared>0 = %d" % len(rows))
    w("V2 旧 walker 走通 = %d" % len(old_ok))
    w("文法 G 走通 = %d" % len(new_ok))
    w("回退（旧走通 → G 失败）= %d" % len(regress))
    for r in regress[:20]:
        w("  REGRESS %s old=%s new_fail=%s" % (r["base"], r["old_ok"], r["new_fail"][:2]))
    w("")
    w("first-attempt 口径 tx-not-eof = %d  → G 走通 %d  仍失败 %d" %
      (len(old_tx), len(gained), len(still)))
    w("任一起点口径 tx-not-eof = %d  → G 走通 %d  仍失败 %d" %
      (len(any_tx), len(gained_any), len(still_any)))
    w("")
    w("first-attempt 128 族 G 走通的挂点数直方：%s" %
      collections.Counter(r["new_ok"]["tx_count"] for r in gained).most_common())
    w("first-attempt 仍失败：")
    for r in still:
        w("  %s declared=%d size=%d old0=%s new=%s" % (
            r["base"], r["declared"], r["size"],
            r["old_fail"][0][1][:80] if r["old_fail"] else None,
            r["new_fail"][:2]))
    w("")
    w("任一口径仍失败：")
    for r in still_any:
        w("  %s declared=%d nfail0=%s new=%s" % (
            r["base"], r["declared"],
            r["old_fail"][0][1][:80] if r["old_fail"] else None,
            r["new_fail"][:2]))

    # 名单：first-attempt tx-not-eof（应对齐报告的 128）
    lst = []
    lst.append("# first-attempt tx-not-eof  %d 份  按 size 升序" % len(old_tx))
    lst.append("# basename  size  declared  G  tx_count  socks")
    for r in sorted(old_tx, key=lambda x: (x["size"], x["base"])):
        if r["new_ok"]:
            socks = ",".join("%s->%s" % a for a in r["new_ok"]["socks"])
            lst.append("%s\t%d\t%d\tG_OK\t%d\t%s" % (
                r["base"], r["size"], r["declared"], r["new_ok"]["tx_count"], socks))
        else:
            lst.append("%s\t%d\t%d\tG_FAIL\t\t" % (r["base"], r["size"], r["declared"]))

    open(os.path.join(OUT, "verify.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    open(os.path.join(OUT, "名单_first_attempt.txt"), "w", encoding="utf-8").write("\n".join(lst) + "\n")

    # 最短 5 份：真挂点段 + 其后（应为空）hex
    hex_lines = []
    for r in sorted(old_tx, key=lambda x: (x["size"], x["base"]))[:5]:
        b = open(r["file"], "rb").read()
        hex_lines.append("=" * 78)
        hex_lines.append("%s size=%d declared=%d G=%s" % (
            r["base"], r["size"], r["declared"], "OK" if r["new_ok"] else "FAIL"))
        if r["new_ok"]:
            at = r["new_ok"]["tx_at"]
            cnt = r["new_ok"]["tx_count"]
            hex_lines.append("真挂点头 @0x%x  [u32 1][u32 %d] + %d×128B  end=0x%x EOF=0x%x left=%d" %
                             (at, cnt, cnt, at + 8 + 128 * cnt, len(b),
                              len(b) - (at + 8 + 128 * cnt)))
            hex_lines.append("socks: %s" % r["new_ok"]["socks"])
            # 头 8B + 第一条名字 32B + 骨名头 16B + 尾巴（空）
            p = at
            end_show = min(len(b), at + 8 + 64)
            while p < end_show:
                chunk = b[p:p + 16]
                hx = " ".join("%02x" % c for c in chunk)
                asc = "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)
                u = C.u32(b, p) if p + 4 <= len(b) else 0
                nm = C.name_at(b, p)
                extra = " u32=%d" % u
                if nm:
                    extra += " NAME='%s'" % nm
                hex_lines.append("%05x  %-47s  |%s|%s" % (p, hx, asc, extra))
                p += 16
            hex_lines.append("挂点段之后到 EOF：%d B（应为 0）" % (len(b) - (at + 8 + 128 * cnt)))
        hex_lines.append("")
    open(os.path.join(OUT, "hex_G_shortest5.txt"), "w", encoding="utf-8").write(
        "\n".join(hex_lines) + "\n")

    summary = {
        "declared": len(rows),
        "v2_ok": len(old_ok),
        "G_ok": len(new_ok),
        "regress": len(regress),
        "txnot_first": len(old_tx),
        "txnot_first_G": len(gained),
        "txnot_first_still": [r["base"] for r in still],
        "txnot_any": len(any_tx),
        "txnot_any_G": len(gained_any),
        "txnot_any_still": [r["base"] for r in still_any],
        "gained_counts": collections.Counter(
            r["new_ok"]["tx_count"] for r in gained).most_common(),
    }
    json.dump(summary, open(os.path.join(OUT, "verify.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("written verify", summary)


if __name__ == "__main__":
    main()
