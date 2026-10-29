"""全库 7,996 份 .mesh 扫描：两套语法各自认多少条记录，新语法在正常文件上误命中多少。
只读，产物写 grammar5/。

语法 A = 现有解析器 geometry.rs::read_node（名 char[32] + 行主序 4x4，m[15]≈1）
语法 B = 本次解出的双名记录（名 char[32] + 同名 char[32] + 17 浮点「w 前置」矩阵 + [N][号][权]）
"""
import os, re, struct, sys, json, time

ROOT = "D:/TLGL"
TREE = f"{ROOT}/.scratch/out/tree"
OUT = f"{ROOT}/.scratch/dyn/grammar5"
OKCHAR = set(range(48, 58)) | set(range(65, 91)) | set(range(97, 123)) | {95, 45, 46}
RUN = re.compile(rb"[!-~]{3,31}")
F16 = struct.Struct("<16f")
F3 = struct.Struct("<3f")

FIVE = {"w1351_model_mj_nan_stone_h01.mesh", "w1351_model_bell_h002.mesh",
        "w1351_model_glass_ani_lf001.mesh", "w1351_model_fazhen_ani_lf001.mesh",
        "w1351_model_ymg01_stone01.mesh"}


def field_name(raw, i):
    """char[32] 名字槽：可打印、NUL 结尾、剩余全 0、前一字不是名字字符。返回名字或 None。"""
    if i > 0 and raw[i - 1] in OKCHAR:
        return None
    f = raw[i:i + 32]
    if len(f) < 32:
        return None
    e = f.find(b"\x00")
    if e < 3:
        return None
    if any(c not in OKCHAR for c in f[:e]):
        return None
    if any(c != 0 for c in f[e:]):
        return None
    return f[:e]


def is_tx(raw, i):
    if i < 32:
        return False
    prev = raw[i - 32:i]
    pl = prev.find(b"\x00")
    pl = 32 if pl < 0 else pl
    return pl >= 3 and all(c in OKCHAR for c in prev[:pl]) and prev[:3].lower() == b"tx_"


def a_record(raw, i):
    """现有 read_node 判据（逐条对齐 geometry.rs）。"""
    if field_name(raw, i) is None:
        return False
    if is_tx(raw, i):
        return False
    if i + 96 > len(raw):
        return False
    m = F16.unpack_from(raw, i + 32)
    if any(abs(v) >= 1e7 or v != v for v in m):
        return False
    if abs(m[15] - 1.0) > 1e-3:
        return False
    R = [list(m[0:3]), list(m[4:7]), list(m[8:11])]
    L = [sum(x * x for x in v) ** 0.5 for v in R]
    mn, mx = min(L), max(L)
    if mn <= 1e-6 or mx / mn > 1.05:
        return False
    for a in range(3):
        for b in range(a + 1, 3):
            if abs(sum(R[a][k] * R[b][k] for k in range(3))) / (L[a] * L[b]) > 0.03:
                return False
    return True


def blen(v):
    return sum(x * x for x in v) ** 0.5


def b_flags(raw, i, vc, bones):
    """新语法，逐层判据的位标记（1<<0 双名 … 1<<5 影响表自洽）。"""
    nm = field_name(raw, i)
    if nm is None:
        return 0
    if field_name(raw, i + 32) != nm:
        return 0
    f = 1 << 0
    if i + 136 > len(raw):
        return f
    ws = [struct.unpack_from("<f", raw, i + 64 + 16 * k)[0] for k in range(4)]
    tris = [struct.unpack_from("<3f", raw, i + 64 + 16 * k + 4) for k in range(4)]
    if all(abs(x) <= 1e-3 for x in ws):
        f |= 1 << 1
    L = [blen(v) for v in tris[:3]]
    mn, mx = min(L), max(L)
    if mn > 1e-6 and mx / mn <= 1.05 and all(x == x and abs(x) < 1e7 for v in tris for x in v):
        ok = True
        for a in range(3):
            for b in range(a + 1, 3):
                if abs(sum(tris[a][k] * tris[b][k] for k in range(3))) / (L[a] * L[b]) > 0.02:
                    ok = False
        if ok:
            f |= 1 << 2
    if abs(struct.unpack_from("<f", raw, i + 128)[0] - 1.0) <= 1e-3:
        f |= 1 << 3
    N = struct.unpack_from("<I", raw, i + 132)[0]
    if 0 < N <= min(vc, 65536):
        ib = raw[i + 136:i + 136 + 4 * N]
        wb = raw[i + 136 + 4 * N:i + 136 + 8 * N]
        if len(ib) == 4 * N and len(wb) == 4 * N:
            ids = struct.unpack("<%dI" % N, ib)
            wts = struct.unpack("<%df" % N, wb)
            if len(set(ids)) == N and all(x < vc for x in ids) and all(
                    w == w and 0.0 <= w <= 1.0001 for w in wts) and not all(w <= 1e-6 for w in wts):
                f |= 1 << 4
                if i + 228 + 8 * N <= len(raw):
                    sc = struct.unpack_from("<3f", raw, i + 212 + 8 * N)
                    if all(abs(x - 100.0) < 1e-3 for x in sc):
                        f |= 1 << 5
    return f


def full_bit():
    return (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)


def scan(raw):
    vc = struct.unpack_from("<I", raw, 0x8C)[0] if len(raw) >= 0x90 else 0
    bones = struct.unpack_from("<I", raw, 0x110)[0] if len(raw) >= 0x114 else 0
    if vc == 0 or vc > 8_000_000:
        return None
    ca = 0
    i = 0
    n = len(raw)
    while i + 96 <= n:
        if a_record(raw, i):
            ca += 1
            i += 96
            continue
        i += 4
    cb = 0
    exact = 0
    loose = 0
    for m in RUN.finditer(raw):
        off = m.start()
        if off % 4:
            continue
        fg = b_flags(raw, off, vc, bones)
        if fg & ((1 << 0) | (1 << 1) | (1 << 2) | (1 << 3)):
            loose += 1
        if fg & full_bit() == full_bit():
            cb += 1
            if fg & (1 << 5):
                exact += 1
        if fg:
            hist[fg] = hist.get(fg, 0) + 1
    return dict(vc=vc, bones=bones, a=ca, b=cb, b_exact=exact, b_loose=loose)


hist = {}


def main():
    t0 = time.time()
    files = []
    for dp, dn, fn in os.walk(TREE):
        for x in fn:
            if x.lower().endswith(".mesh"):
                files.append(os.path.join(dp, x))
    files.sort()
    rows = []
    for k, p in enumerate(files):
        try:
            raw = open(p, "rb").read()
        except Exception as ex:
            rows.append((p, "READ_FAIL " + str(ex), 0, 0, 0, 0, 0))
            continue
        r = scan(raw)
        if r is None:
            rows.append((p, "BADHEAD", 0, 0, 0, 0, 0))
        else:
            rows.append((p, "", r["vc"], r["bones"], r["a"], r["b"], r["b_exact"]))
        if (k + 1) % 800 == 0:
            el = time.time() - t0
            with open(os.path.join(OUT, "scan_progress.txt"), "w", encoding="utf-8") as fh:
                fh.write(f"{k+1}/{len(files)} elapsed={el:.0f}s eta={el/(k+1)*len(files)-el:.0f}s\n")
    with open(os.path.join(OUT, "scanall.tsv"), "w", encoding="utf-8") as fh:
        fh.write("path\tnote\tvc\tbones\ta_records\tb_records\tb_with_scale100\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")
    json.dump(hist, open(os.path.join(OUT, "b_flag_hist.json"), "w"), indent=1)
    open(os.path.join(OUT, "scan_done.txt"), "w").write(
        f"done files={len(files)} elapsed={time.time()-t0:.0f}s\n")
    print("DONE", len(files), round(time.time() - t0))


if __name__ == "__main__":
    main()
