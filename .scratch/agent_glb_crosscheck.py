"""Cross-check the Rust .mesh parser against the independent Python reference.

Reads the TSV emitted by `mesh_gate` (Rust) and re-derives every field from the raw
bytes with the Python locator (agent_fmt_lib) + the same content-validated stream
model. Any disagreement is printed; agreement on 7,996/7,996 is the gate.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, r"D:\TLGL\.scratch")
import agent_fmt_lib as lib  # noqa: E402

ROOT = Path(r"D:\TLGL\.scratch\out\tree")
TSV = Path(r"D:\TLGL\.scratch\agent_glb_mesh.tsv")
OUT = Path(r"D:\TLGL\.scratch\agent_glb_crosscheck.txt")
L = []


def py_parse(raw):
    n = len(raw)
    if n < 0x118:
        return None, "too_short"
    vc, fc, smf = struct.unpack_from("<3I", raw, 0x8C)
    sm = smf if smf else 1
    if vc > 8_000_000 or fc > 8_000_000 or sm > 64 or fc == 0:
        return None, "implausible"
    pos_end = 0x118 + vc * 12
    if pos_end > n:
        return None, "truncated_positions"
    hit = lib.locate(raw, vc, fc, sm, pos_end)
    if hit is None:
        return None, "not_located"
    p, counts = hit
    middle = p - pos_end
    # stream model, same content checks as the Rust side
    rem = middle
    norms = 0
    cursor = 0
    if rem >= vc * 12:
        f = struct.unpack_from("<%df" % (vc * 3), raw, pos_end)
        unit = all(abs((f[i] * f[i] + f[i + 1] ** 2 + f[i + 2] ** 2) ** 0.5 - 1.0) <= 0.01
                   for i in range(0, vc * 3, 3))
        if unit:
            norms = vc
            cursor = vc * 12
    uv = 0
    if norms and rem - cursor >= vc * 8:
        g = struct.unpack_from("<%df" % (vc * 2), raw, pos_end + cursor)
        if all(abs(v) <= 4096.0 for v in g):
            uv = 1
            cursor += vc * 8
    ft = (vc > 0) and (rem - cursor == fc * 2)
    if ft:
        cursor += fc * 2
    idx = struct.unpack_from("<%dH" % (fc * 3), raw, p + 4 * sm)
    return {
        "n": n, "vc": vc, "fc": fc, "sm": smf, "middle": middle,
        "trailing": n - (p + 4 * sm + fc * 6), "uv_sets": uv, "ft": 1 if ft else 0,
        "leftover": rem - cursor, "nrm": norms, "counts": "+".join(str(c) for c in counts),
        "idx_ok": all(i < vc for i in idx),
    }, "ok"


def main():
    rows = 0
    diffs = []
    err_rows = 0
    stats = {"n": 0, "nrm": 0, "uv": 0, "ft": 0, "left": 0, "idx_ok": 0}
    for line in TSV.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            diffs.append(("malformed", line))
            continue
        rel, status = parts[0], parts[1]
        rows += 1
        raw = (ROOT / rel).read_bytes()
        exp, why = py_parse(raw)
        if status == "ERR" or exp is None:
            err_rows += 1
            if not (status == "ERR" and exp is None):
                diffs.append(("one-side-fail", rel, status, why))
            continue
        got = {
            "n": int(parts[2]), "vc": int(parts[3]), "fc": int(parts[4]), "sm": int(parts[5]),
            "middle": int(parts[6]), "trailing": int(parts[7]), "uv_sets": int(parts[8]),
            "ft": int(parts[9]), "leftover": int(parts[10]), "nrm": int(parts[11]),
            "counts": parts[12],
        }
        for k in ("n", "vc", "fc", "sm", "middle", "trailing", "uv_sets", "ft", "leftover", "nrm", "counts"):
            if got[k] != exp[k]:
                diffs.append((k, rel, got[k], exp[k]))
        if not exp["idx_ok"]:
            diffs.append(("idx_range", rel))
        stats["n"] += 1
        stats["nrm"] += exp["nrm"] > 0
        stats["uv"] += exp["uv_sets"]
        stats["ft"] += exp["ft"]
        stats["left"] += exp["leftover"] > 0
        stats["idx_ok"] += exp["idx_ok"]

    L.append(f"tsv rows            : {rows}")
    L.append(f"both parsed         : {stats['n']}")
    L.append(f"either side refused : {err_rows}")
    L.append(f"normals verified    : {stats['nrm']}")
    L.append(f"uv set 0 verified   : {stats['uv']}")
    L.append(f"face table (2*fc)   : {stats['ft']}")
    L.append(f"unexplained middle  : {stats['left']}")
    L.append(f"indices in range    : {stats['idx_ok']}")
    L.append(f"field disagreements : {len(diffs)}")
    for d in diffs[:40]:
        L.append("  " + repr(d))
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:10]))


if __name__ == "__main__":
    main()
