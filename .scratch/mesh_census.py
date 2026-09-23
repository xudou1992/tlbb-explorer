"""Census: how many real .mesh files can the current geometry parser actually draw?

Replicates crates/core/src/preview/geometry.rs::parse_geometry byte-for-byte in
Python and runs it over every named .mesh under .scratch/out/tree.
"""
import json
import os
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else r"D:\TLGL\.scratch\out\tree")
OUT = Path(r"D:\TLGL\.scratch\mesh_census.txt")

MAX = 8_000_000


def u32(b, off):
    if off + 4 > len(b):
        return None
    return struct.unpack_from("<I", b, off)[0]


def locate(raw, lo, fc, vc):
    need = 4 + fc * 3 * 2
    if fc == 0 or len(raw) < need:
        return None
    hi = len(raw) - need
    want = struct.pack("<I", fc)
    at = lo
    while at <= hi:
        p = raw.find(want, at, hi + 4)
        if p < 0:
            return None
        blk = raw[p + 4 : p + need]  # need already counts the 4-byte face field
        ok = True
        for i in range(0, len(blk), 2):
            if struct.unpack_from("<H", blk, i)[0] >= vc:
                ok = False
                break
        if ok:
            return p
        at = p + 4
    return None


def parse(raw):
    """-> (ok: bool, reason: str, meta: dict)"""
    n = len(raw)
    if n < 0x118:
        return False, "shorter_than_header", {"size": n}
    tag = raw[0x40:0x44]
    banner = raw[:8] == b"Copyright "
    vc, fc, sm = u32(raw, 0x8C), u32(raw, 0x90), u32(raw, 0x94)
    meta = {"size": n, "vc": vc, "fc": fc, "sm": sm, "tag": tag.decode("latin1"), "banner": banner}
    if vc is None or fc is None or vc > MAX or fc > MAX:
        return False, "implausible_counts", meta
    pos_end = 0x118 + vc * 12
    if pos_end > n:
        return False, "position_stream_truncated", meta
    static_idx = pos_end + vc * 20
    idx = None
    if u32(raw, static_idx) == fc:
        idx = static_idx
    else:
        idx = locate(raw, pos_end, fc, vc)
    if idx is None:
        return False, "no_self_consistent_index_block", meta
    middle = idx - pos_end
    meta["middle"] = middle
    meta["stride"] = round(middle / vc, 2) if vc else 0
    meta["static"] = middle == vc * 20
    meta["trailing"] = n - (idx + 4 + fc * 6)
    return True, "ok" if meta["static"] else "ok_no_normals", meta


def main():
    files = []
    for dirpath, _dirs, names in os.walk(ROOT):
        for nm in names:
            if nm.lower().endswith(".mesh"):
                files.append(Path(dirpath) / nm)
    files.sort()

    reasons = Counter()
    strides = Counter()
    tags = Counter()
    succ_sm = Counter()
    fail_sm = Counter()
    sizes = Counter()
    samples = {}
    big_ok = 0
    total_vc = total_fc = 0

    for f in files:
        try:
            raw = f.read_bytes()
        except OSError as e:
            reasons["read_error"] += 1
            continue
        ok, reason, meta = parse(raw)
        reasons[reason] += 1
        tags[meta.get("tag", "?")] += 1
        sm = meta.get("sm")
        (succ_sm if ok else fail_sm)[sm] += 1
        if ok:
            total_vc += meta["vc"]
            total_fc += meta["fc"]
            strides[meta["stride"]] += 1
            if meta["vc"] > 20000:
                big_ok += 1
        samples.setdefault(reason, (str(f.relative_to(ROOT)), meta))
        if f.stat().st_size < 0x118:
            sizes["<0x118"] += 1
        elif len(raw) < 0x118 + (meta.get("vc") or 0) * 12:
            sizes["pos_trunc"] += 1
        else:
            sizes["pos_ok"] += 1

    n = len(files)
    ok_n = sum(v for k, v in reasons.items() if k.startswith("ok"))
    lines = []
    lines.append(f"total .mesh files scanned: {n}")
    lines.append(f"parseable (positions+indices located): {ok_n}  ({ok_n*100.0/n:.1f}%)")
    lines.append(f"drawable with file normals+uv (static layout): {reasons['ok']}")
    lines.append(f"drawable but no normals (skinned middle): {reasons['ok_no_normals']}")
    lines.append(f"vertices drawable: {total_vc:,} / triangles: {total_fc:,} / models >20k verts: {big_ok}")
    lines.append("")
    lines.append("failure / outcome reasons:")
    for k, v in reasons.most_common():
        lines.append(f"  {k:34s} {v:6d}  {v*100.0/n:5.1f}%   e.g. {samples[k][0]}  {samples[k][1]}")
    lines.append("")
    lines.append("middle-segment bytes per vertex (successful parses, top 12):")
    for k, v in strides.most_common(12):
        lines.append(f"  {k:8} {v:6d}")
    lines.append("")
    lines.append("type tag @0x40:")
    for k, v in tags.most_common(8):
        lines.append(f"  {k!r:12} {v:6d}")
    lines.append("")
    lines.append("submesh/material-slot count distribution:")
    lines.append("  parsed ok : " + ", ".join(f"sm={k}:{v}" for k, v in succ_sm.most_common(8)))
    lines.append("  failed    : " + ", ".join(f"sm={k}:{v}" for k, v in fail_sm.most_common(8)))

    text = "\n".join(lines)
    OUT.write_text(text, encoding="utf-8")
    json.dump(
        {"reasons": dict(reasons), "strides": {str(k): v for k, v in strides.most_common(20)},
         "tags": {k: v for k, v in tags.most_common()}, "files": n},
        open(r"D:\TLGL\.scratch\mesh_census.json", "w"),
        ensure_ascii=False, indent=1,
    )
    print(text)


if __name__ == "__main__":
    main()
