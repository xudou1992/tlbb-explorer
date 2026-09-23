"""Shared locator for the .mesh submesh index array (agent_fmt_* scripts).

Layout hypothesis (validated here):
    0x118              positions            vc * 3 * f32
    0x118+vc*12        "middle" streams     (normals/uv/... , variable)
    p                  u32 faceCount[sm]    4-byte stride, sum(counts)==fc
    p + 4*sm           indices              fc * 3 * u16, every value < vc
    len(raw)           (optional trailing region)
"""
import numpy as np


def count_array_positions(raw, vc, fc, sm, pos_end, cap=64):
    """all p >= pos_end where u32[sm] (4-byte stride) sums to fc and the following
    fc*3 u16 are all < vc; ascending by p"""
    n = len(raw)
    need = 4 * sm + 6 * fc
    if fc == 0 or n - pos_end < need:
        return []
    out = []
    seen = set()
    for r in range(4):
        off = pos_end + ((r - pos_end) % 4)
        cnt = (n - off) // 4
        if cnt < sm or off + need > n:
            continue
        b = np.frombuffer(raw, dtype="<u4", count=cnt, offset=off).astype(np.int64)
        cs = np.concatenate(([0], np.cumsum(b)))
        sums = cs[sm:] - cs[:-sm]
        for i in np.nonzero(sums == fc)[0]:
            i = int(i)
            p = off + 4 * i
            if p + need > n or p in seen:
                continue
            blk = b[i:i + sm]
            if int(blk.max()) > fc:
                continue
            idx = np.frombuffer(raw, dtype="<u2", count=fc * 3, offset=p + 4 * sm)
            if int(idx.max()) >= vc:
                continue
            seen.add(p)
            out.append((p, tuple(int(x) for x in blk)))
            if len(out) >= cap:
                break
    out.sort(key=lambda t: t[0])
    return out


def locate(raw, vc, fc, sm, pos_end):
    """first (earliest) validating position -> (p, counts) or None"""
    r = count_array_positions(raw, vc, fc, sm, pos_end, cap=4)
    return r[0] if r else None
