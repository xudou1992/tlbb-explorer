# -*- coding: utf-8 -*-
"""只读解析：.mesh 尾部层级（孩子名单）+ 96B 绑定逆矩阵，.ani 第 0 帧局部平移。

口径（不得翻案）：
- 96B 存储矩阵 S 是世界绑定 B 的逆；骨位 = inverse(S) 的平移（末行 tx,ty,tz）。
- 父链只从孩子名单反推，不把条目标志当父索引。
- .ske 不是骨架，这里不读。
布局对齐 tlbb-explorer geometry.rs::parse_hierarchy / anim.rs::parse_ani /
pose.rs::bind_worlds / mat_inverse_affine（行向量 D3DX）。本文件是取证复现，
不改产品代码。
"""
from __future__ import annotations

import math
import os
import re
import struct

NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")
NODE_RECORD = 96
NAME_FIELD = 32
BONE_COUNT_AT = 0x110


def u32(raw: bytes, off: int) -> int | None:
    if off + 4 > len(raw):
        return None
    return struct.unpack_from("<I", raw, off)[0]


def f32(raw: bytes, off: int) -> float | None:
    if off + 4 > len(raw):
        return None
    return struct.unpack_from("<f", raw, off)[0]


def name_at(raw: bytes, off: int) -> str | None:
    if off < 1 or off + 32 > len(raw):
        return None
    prev = raw[off - 1]
    if (48 <= prev <= 57) or (65 <= prev <= 90) or (97 <= prev <= 122) or prev in (95, 45, 46):
        return None
    m = NAME_OK.match(raw, off)
    if not m:
        return None
    s = m.group()
    if len(s) > 31 or raw[off + len(s)] != 0:
        return None
    if any(x != 0 for x in raw[off + len(s) : off + 32]):
        return None
    return s.decode("ascii")


def _ortho3(m, min_len: float, rel_dot: float | None, abs_dot: float | None) -> bool:
    rows = (m[0:3], m[4:7], m[8:11])
    lens = [math.sqrt(sum(v * v for v in r)) for r in rows]
    mn, mx = min(lens), max(lens)
    if mn <= min_len or mx / mn > 1.05:
        return False
    for i in range(3):
        for k in range(i + 1, 3):
            d = sum(rows[i][t] * rows[k][t] for t in range(3))
            if rel_dot is not None:
                if abs(d) / (lens[i] * lens[k]) > rel_dot:
                    return False
            if abs_dot is not None:
                if abs(d) > abs_dot:
                    return False
    return True


def record96(raw: bytes, off: int):
    if off + 96 > len(raw):
        return None
    nm = name_at(raw, off)
    if nm is None:
        return None
    m = struct.unpack_from("<16f", raw, off + 32)
    if not all(math.isfinite(v) and abs(v) < 1e7 for v in m):
        return None
    if abs(m[15] - 1.0) > 1e-3:
        return None
    if not _ortho3(m, 1e-6, 0.03, None):
        return None
    return nm, m


def is_u92(raw: bytes, off: int) -> bool:
    if off + 88 > len(raw):
        return False
    d = f32(raw, off)
    if d is None or not (0.9 <= d <= 1.1):
        return False
    a = f32(raw, off + 20)
    b = f32(raw, off + 40)
    c = f32(raw, off + 60)
    if a is None or b is None or c is None:
        return False
    if abs(a - d) > 1e-6 or abs(b - d) > 1e-6 or abs(c - 1.0) > 1e-3:
        return False
    for o in (76, 80, 84):
        v = f32(raw, off + o)
        if v is None or abs(v - 100.0) > 1e-2:
            return False
    return True


def is_mat64(raw: bytes, off: int) -> bool:
    if off + 64 > len(raw):
        return False
    m = struct.unpack_from("<16f", raw, off)
    if not all(math.isfinite(v) and abs(v) < 1e7 for v in m):
        return False
    if abs(m[3]) > 1e-3 or abs(m[7]) > 1e-3 or abs(m[11]) > 1e-3 or abs(m[15] - 1.0) > 1e-3:
        return False
    return _ortho3(m, 1e-4, None, 1e-2)


def is_inf(raw: bytes, off: int, vc: int) -> bool:
    n = u32(raw, off)
    if n is None:
        return False
    if n == 0:
        return True
    if n > vc or n > 200000 or off + 4 + 8 * n > len(raw):
        return False
    seen = set()
    for k in range(n):
        v = u32(raw, off + 4 + 4 * k)
        if v is None or v >= vc or v in seen:
            return False
        seen.add(v)
    for k in range(n):
        w = f32(raw, off + 4 + 4 * n + 4 * k)
        if w is None or not math.isfinite(w) or not (-1e-3 <= w <= 1.001):
            return False
    return True


def _skip_blocks(raw: bytes, p: int, vc: int):
    """吞掉 u92 / 64B / 影响表。返回 (newpos, n_inf_nonzero)。"""
    ninf = 0
    while True:
        if is_u92(raw, p):
            p += 88
            continue
        if is_mat64(raw, p):
            p += 64
            continue
        n = u32(raw, p)
        if n is not None and is_inf(raw, p, vc):
            if n > 0:
                ninf += 1
            p += 4 + 8 * n
            continue
        break
    return p, ninf


def try_entry(raw: bytes, off: int, vc: int):
    p = off
    own = record96(raw, p)
    if own is not None:
        p += NODE_RECORD
    p, ninf = _skip_blocks(raw, p, vc)
    flag = u32(raw, p)
    if flag is None:
        return None
    p += 4
    nm1 = name_at(raw, p)
    nm2 = name_at(raw, p + 32) if p + 32 < len(raw) else None
    if nm1 is None or nm1 != nm2:
        return None
    if own is not None and own[0] != nm1:
        return None
    p += 64
    c = u32(raw, p)
    if c is None or c > 4096:
        return None
    p += 4
    children = []
    for _ in range(c):
        rec = record96(raw, p)
        if rec is not None:
            children.append((rec[0], rec[1]))
            p += NODE_RECORD
        else:
            cn = name_at(raw, p)
            if cn is None:
                return None
            children.append((cn, None))
            p += 32
    return {
        "name": nm1,
        "flag": flag,
        "own_bind": own[1] if own else None,
        "children": children,
        "ninf": ninf,
    }, p


def try_sockets(raw: bytes, start: int, vc: int):
    p = start
    while True:
        if u32(raw, p) == 1:
            count = u32(raw, p + 4)
            if count is not None and count <= 4096:
                end = p + 8 + 128 * count
                if end == len(raw):
                    ok = True
                    q = p + 8
                    for _ in range(count):
                        if name_at(raw, q) is None or name_at(raw, q + 32) is None:
                            ok = False
                            break
                        m = struct.unpack_from("<16f", raw, q + 64)
                        if not all(math.isfinite(v) and abs(v) < 1e7 for v in m) or abs(m[15] - 1.0) > 1e-3:
                            ok = False
                            break
                        q += 128
                    if ok:
                        return True, end
        if is_u92(raw, p):
            p += 88
            continue
        if is_mat64(raw, p):
            p += 64
            continue
        n = u32(raw, p)
        if n is not None and is_inf(raw, p, vc):
            p += 4 + 8 * n
            continue
        return None


def walk_tail(raw: bytes, start: int, vc: int):
    p = start
    entries = []
    ninf_total = 0
    while p < len(raw):
        got = try_entry(raw, p, vc)
        if got is not None:
            e, p = got
            ninf_total += e["ninf"]
            entries.append(e)
            continue
        if record96(raw, p) is not None:
            p += NODE_RECORD
            continue
        sock = try_sockets(raw, p, vc)
        if sock is not None:
            _, end = sock
            if end != len(raw):
                return None
            return entries, ninf_total
        return None
    if p != len(raw):
        return None
    return entries, ninf_total


def parse_hierarchy(raw: bytes):
    if len(raw) < BONE_COUNT_AT + 4:
        return None
    declared = u32(raw, BONE_COUNT_AT)
    vc = u32(raw, 0x8C) or 0
    if not declared or declared > 4096:
        return None
    starts = []
    i = 0
    while i + NODE_RECORD <= len(raw):
        rec = record96(raw, i)
        if rec is not None:
            if rec[0] == "origin":
                starts.append(i)
            i += NODE_RECORD
        else:
            i += 4
    variants = []
    i = 0
    while i + 4 + 2 * NAME_FIELD <= len(raw):
        if u32(raw, i) == 0xFFFFFFFF:
            nm = name_at(raw, i + 4)
            if nm is not None and name_at(raw, i + 4 + NAME_FIELD) == nm:
                variants.append(i)
        i += 4
    walked = None
    ninf = 0
    for start in starts + variants:
        got = walk_tail(raw, start, vc)
        if got is None:
            continue
        entries, ninf = got
        if len(entries) == declared:
            walked = entries
            break
    if walked is None:
        return None
    names = [e["name"] for e in walked]
    if len(set(names)) != len(names):
        return None
    index = {nm: i for i, nm in enumerate(names)}
    parent = [None] * len(walked)
    children_idx = [[] for _ in walked]
    for i, e in enumerate(walked):
        for cn, _cb in e["children"]:
            j = index.get(cn)
            if j is None or parent[j] is not None:
                return None
            parent[j] = i
            children_idx[i].append(j)
    if sum(1 for p in parent if p is None) != 1:
        return None
    for i in range(len(walked)):
        seen = set()
        cur = i
        while cur is not None:
            if cur in seen:
                return None
            seen.add(cur)
            cur = parent[cur]
    binds = [e["own_bind"] for e in walked]
    for e in walked:
        for cn, cb in e["children"]:
            if cb is not None:
                j = index[cn]
                if binds[j] is None:
                    binds[j] = cb
    bones = []
    for i, e in enumerate(walked):
        bones.append(
            {
                "name": e["name"],
                "parent": parent[i],
                "bind": binds[i],
                "children": children_idx[i],
            }
        )
    return {
        "bones": bones,
        "has_weights": ninf > 0,
        "kind": "origin" if (starts and walked is not None) else "root-flag",
        "declared": declared,
        "vc": vc,
    }


def mat_identity():
    m = [0.0] * 16
    m[0] = m[5] = m[10] = m[15] = 1.0
    return m


def mat_mul(a, b):
    o = [0.0] * 16
    for r in range(4):
        for c in range(4):
            o[r * 4 + c] = (
                a[r * 4] * b[c]
                + a[r * 4 + 1] * b[4 + c]
                + a[r * 4 + 2] * b[8 + c]
                + a[r * 4 + 3] * b[12 + c]
            )
    return o


def mat_inverse_affine(m):
    if not all(math.isfinite(v) for v in m) or abs(m[15] - 1.0) > 1e-3:
        return None
    a, b, c = m[0], m[1], m[2]
    d, e, f = m[4], m[5], m[6]
    g, h, i = m[8], m[9], m[10]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if not math.isfinite(det) or abs(det) < 1e-12:
        return None
    iv = 1.0 / det
    r00, r01, r02 = (e * i - f * h) * iv, -(b * i - c * h) * iv, (b * f - c * e) * iv
    r10, r11, r12 = -(d * i - f * g) * iv, (a * i - c * g) * iv, -(a * f - c * d) * iv
    r20, r21, r22 = (d * h - e * g) * iv, -(a * h - b * g) * iv, (a * e - b * d) * iv
    t0, t1, t2 = m[12], m[13], m[14]
    o = [0.0] * 16
    o[0], o[1], o[2] = r00, r01, r02
    o[4], o[5], o[6] = r10, r11, r12
    o[8], o[9], o[10] = r20, r21, r22
    o[12] = -(t0 * r00 + t1 * r10 + t2 * r20)
    o[13] = -(t0 * r01 + t1 * r11 + t2 * r21)
    o[14] = -(t0 * r02 + t1 * r12 + t2 * r22)
    o[15] = 1.0
    return o


def bind_worlds(bones):
    n = len(bones)
    worlds = [mat_identity() for _ in range(n)]
    done = [False] * n
    for _ in range(n + 1):
        progress = False
        for i in range(n):
            if done[i]:
                continue
            s = bones[i]["bind"]
            if s is not None:
                worlds[i] = mat_inverse_affine(s) or mat_identity()
                done[i] = True
                progress = True
            else:
                p = bones[i]["parent"]
                if p is None:
                    worlds[i] = mat_identity()
                    done[i] = True
                    progress = True
                elif done[p]:
                    worlds[i] = worlds[p]
                    done[i] = True
                    progress = True
        if not progress:
            break
    return worlds


def bind_locals(bones, worlds):
    n = len(bones)
    locals_ = [mat_identity() for _ in range(n)]
    for i, b in enumerate(bones):
        p = b["parent"]
        if p is None:
            locals_[i] = worlds[i]
        else:
            pinv = mat_inverse_affine(worlds[p])
            if pinv is None:
                locals_[i] = mat_identity()
            else:
                locals_[i] = mat_mul(worlds[i], pinv)
    return locals_


def trans(m):
    return (m[12], m[13], m[14])


def vlen(t):
    return math.sqrt(t[0] * t[0] + t[1] * t[1] + t[2] * t[2])


def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def parse_ani(raw: bytes):
    if len(raw) < 0xca:
        return None
    if raw[0x40:0x43] != b"ani":
        return None
    bones = struct.unpack_from("<H", raw, 0xBA)[0]
    bones2 = struct.unpack_from("<H", raw, 0xBE)[0]
    frames = struct.unpack_from("<H", raw, 0xC2)[0]
    if bones != bones2 or bones == 0 or frames == 0 or bones > 512 or frames > 8192:
        return None
    tick = struct.unpack_from("<f", raw, 0xC6)[0]
    names = []
    for i in range(bones):
        o = 0xF0 + i * 30
        slot = raw[o : o + 30] if o + 30 <= len(raw) else b""
        if not slot:
            names.append("")
            continue
        end = slot.find(b"\x00")
        if end < 0:
            end = 30
        bts = slot[:end]
        clean = bool(bts) and all(
            (48 <= c <= 57) or (65 <= c <= 90) or (97 <= c <= 122) or c in (95, 45, 46) for c in bts
        )
        names.append(bts.decode("ascii") if clean else "")
    block = frames * 32
    total = bones * block
    if len(raw) < total:
        return None
    base = len(raw) - total
    if base < 0xF0 + bones * 30:
        return None
    tracks = []
    for i, name in enumerate(names):
        o = base + i * block
        rots = []
        poss = []
        scas = []
        for f in range(frames):
            x, y, z, w = struct.unpack_from("<4f", raw, o + f * 16)
            rots.append((x, y, z, w))
        po = o + frames * 16
        for f in range(frames):
            x, y, z = struct.unpack_from("<3f", raw, po + f * 12)
            poss.append((x, y, z))
        so = o + frames * 28
        for f in range(frames):
            scas.append(struct.unpack_from("<f", raw, so + f * 4)[0])
        tracks.append({"bone": name, "rotations": rots, "positions": poss, "scales": scas})
    return {"bones": bones, "frames": frames, "tick": tick, "tracks": tracks}


def load_mesh(path: str):
    raw = open(path, "rb").read()
    h = parse_hierarchy(raw)
    if h is None:
        return None
    worlds = bind_worlds(h["bones"])
    locals_ = bind_locals(h["bones"], worlds)
    h["worlds"] = worlds
    h["locals"] = locals_
    h["path"] = path
    h["size"] = len(raw)
    return h


def load_ani(path: str):
    raw = open(path, "rb").read()
    a = parse_ani(raw)
    if a is None:
        return None
    a["path"] = path
    a["size"] = len(raw)
    return a


def pick_idle(ani_paths):
    ranked = []
    for p in ani_paths:
        n = os.path.basename(p).lower()
        score = 50
        if "_idle01." in n:
            score = 0
        elif n.endswith("_idle.ani"):
            score = 1
        elif "_fight_idle01." in n:
            score = 2
        elif "_idle02." in n:
            score = 3
        elif "_stand." in n:
            score = 4
        elif "_idle" in n:
            score = 5
        ranked.append((score, len(n), p))
    ranked.sort()
    return ranked[0][2] if ranked else None
