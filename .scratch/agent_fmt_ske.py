"""Task B2: is there any binary bone-transform data inside .ske?

.ske is a JBCF container (see jbcf.py).  Per file we measure:
  * strings in the string table, how many look like bone names
  * bytes between the 16B header + root chunk and the string table ("body")
  * bytes after the string table (EOF slack)
  * does body size scale with bone count?
  * chunk-tree walk (is the body structure or raw float data?)
  * f32 scan of the body: unit-quaternion-like / small-vector-like runs
"""
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"D:\TLGL\.scratch")
import jbcf  # noqa: E402

TREE = Path(r"D:\TLGL\.scratch\out\tree")
OUT = Path(r"D:\TLGL\.scratch\agent_fmt_ske.txt")
L = []


def log(*a):
    L.append(" ".join(str(x) for x in a))


def r8(n):
    return n if not n & 7 else n + 8 - (n & 7)


def walk(raw, off, end, depth, lines, maxd=6, budget=None):
    """JBCF chunk walk: [u32 id][u32 size][payload size bytes]"""
    if budget is not None and budget[0] <= 0:
        return
    p = off
    while p + 8 <= end and p + 8 <= len(raw):
        cid, size = struct.unpack_from("<2I", raw, p)
        payload = p + 8
        stop = payload + size
        if stop > end or size > (1 << 26):
            lines.append("  " * depth + f"@{p:#x} BAD id={cid} size={size} end={end:#x}")
            return
        note = ""
        if depth >= maxd:
            note = " (depth cap)"
        else:
            # try to interpret as nested chunks
            sub = []
            ok = _looks_structured(raw, payload, stop)
            if ok:
                walk(raw, payload, stop, depth + 1, lines, maxd)
                note = ""
                lines.append("  " * depth + f"@{p:#x} chunk id={cid} size={size}")
                p = payload + r8(size) if False else p + 8 + size
                continue
            else:
                note = " (data)"
        lines.append("  " * depth + f"@{p:#x} chunk id={cid} size={size}{note}")
        p = payload + size
        # chunks appear to be 8-byte aligned inside
        while p % 8 and p < end:
            p += 1


def _looks_structured(raw, off, end):
    n = 0
    p = off
    while p + 8 <= end:
        cid, size = struct.unpack_from("<2I", raw, p)
        if cid > 4096 or size > (end - p) or size > (1 << 24):
            return False
        p += 8 + size
        while p % 8 and p < end:
            p += 1
        n += 1
        if n > 40:
            return False
    return n > 0 and p == end


def body_stats(raw, so, strs):
    """float-ish scan of the region between the root-chunk header and the strtab"""
    body = raw[24:so]
    if len(body) < 16:
        return None
    nf = len(body) // 4
    try:
        vals = struct.unpack("<%df" % nf, body[:nf * 4])
    except struct.error:
        return None
    finite = [v for v in vals if v == v and abs(v) < 1e10]
    nq = 0
    for i in range(0, len(vals) - 3):
        a, b, c, d = vals[i:i + 4]
        if not all(v == v for v in (a, b, c, d)):
            continue
        s = a * a + b * b + c * c + d * d
        if 0.98 < s < 1.02 and max(abs(a), abs(b), abs(c), abs(d)) <= 1.0:
            nq += 1
    return {"body": len(body), "nwords": nf, "finite": len(finite), "frac_small":
            sum(1 for v in vals if -30.0 < v < 30.0) / max(1, nf), "quat_hits": nq}


def bone_like(names):
    kw = ("bip", "bone", "pelvis", "spine", "shoulder", "arm", "hand", "leg", "foot",
          "head", "chest", "waist", "thigh", "calf", "finger", "clav", "forearm", "neck")
    return [s for s in names if any(k in s.lower() for k in kw)]


def main():
    files = sorted(TREE.rglob("*.ske"))
    log(f".ske corpus: {len(files)}")
    st = Counter()
    nstr_h = Counter()
    slack_h = Counter()
    body_h = Counter()
    ratio = []
    fails = []
    parsed = []
    for f in files:
        raw = f.read_bytes()
        try:
            hdr, so, flag, strs = jbcf.parse(raw)
        except Exception as e:  # noqa
            fails.append((f.name, len(raw), str(e)[:60]))
            st["parse_fail"] += 1
            continue
        st["parse_ok"] += 1
        root_size = hdr[5]
        body = so - 24
        nsl = len(raw) - (so + 8 + struct.unpack_from("<I", raw, so + 4)[0])
        slack_h[min(nsl, 20)] += 1
        nstr_h[min(len(strs), 30)] += 1
        body_h[min(body, 4096)] += 1
        bl = bone_like([s for s, _ in strs])
        parsed.append((f, len(raw), so, len(strs), body, len(bl), flag, strs))
    log(f"parse: {dict(st)}  failures sample: {fails[:8]}")
    log(f"EOF slack after strtab (capped 20): {slack_h.most_common(12)}")
    log(f"strings per file (capped 30): {nstr_h.most_common(14)}")
    log(f"body bytes = strtab_off-24 (top 14): {body_h.most_common(14)}")

    # does the body grow with the number of strings?
    pts = [(p[3], p[4], p[0].name) for p in parsed if p[3] > 0]
    pts.sort()
    if pts:
        import statistics
        xs = [a for a, _, _ in pts]
        ys = [b for _, b, _ in pts]
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        vx = sum((x - mx) ** 2 for x in xs) ** 0.5
        vy = sum((y - my) ** 2 for y in ys) ** 0.5
        r = cov / (vx * vy) if vx and vy else 0
        log(f"corr(strings, body_bytes) = {r:.3f}  n={len(pts)}  "
            f"body range {min(ys)}..{max(ys)}  strings range {min(xs)}..{max(xs)}")
        # per-string body bytes distribution
        per = sorted(b / s for s, b, _ in pts)
        log(f"body_bytes/strings: p10={per[len(per)//10]:.1f} p50={per[len(per)//2]:.1f} p90={per[len(per)*9//10]:.1f}")
        perb = sorted(b / max(1, bl) for _, _, _, _, b, bl in [(p[0].name, 0, 0, p[3], p[4], p[5]) for p in parsed] if bl)
        if perb:
            log(f"body_bytes/bone_like_strings: n={len(perb)} p50={perb[len(perb)//2]:.1f}")

    log("")
    log("=== float scan of body region ===")
    qtot = 0
    qq = 0
    for p in parsed[:400]:
        f, n, so, ns, body, bl, flag, strs = p
        s = body_stats(f.read_bytes(), so, strs)
        if not s:
            continue
        qtot += 1
        if s["quat_hits"]:
            qq += 1
        if s["frac_small"] > 0.5 and body > 64:
            log(f"  small-float-rich: {f.name} size={n} body={body} str={ns} {s}")
    log(f"bodies scanned={qtot} with any unit-quaternion-like f32 run={qq}")

    log("")
    log("=== chunk-tree dumps ===")
    picks = sorted(parsed, key=lambda t: -t[4])[:2] + sorted(parsed, key=lambda t: t[4])[:2]
    picks += [p for p in parsed if "zhang" in p[0].name.lower()][:1]
    for p in picks:
        f, n, so, ns, body, bl, flag, strs = p
        raw = f.read_bytes()
        log(f"\n--- {f.name} size={n} strtab@0x{so:X} strings={ns} bone_like={bl} flag={flag}")
        log(f"    hdr={hdr if (hdr := None) else list(struct.unpack('<6I', raw[:24]))}")
        lines = []
        walk(raw, 16, so, 0, lines)
        L.extend(lines[:60])
        log("    strings: " + ", ".join(s for s, _ in strs[:40]))
        log("    tail after strtab: " + raw[-16:].hex(" "))
        log("    body first 128B: " + raw[24:min(24 + 128, so)].hex(" "))

    log("")
    log("=== biggest .ske files by size ===")
    for p in sorted(parsed, key=lambda t: -t[1])[:8]:
        log(f"  {p[0]} size={p[1]} strtab@0x{p[2]:X} strings={p[3]} body={p[4]} bone_like={p[5]}")
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("wrote", OUT, len(L))


if __name__ == "__main__":
    main()
