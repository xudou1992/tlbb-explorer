"""coord_* 审计共用的 .scene 解析库 —— 逐字节复刻 crates/core/src/preview/scene.rs 的口径。

复刻点（与 Rust 一一对应，不许任何"顺手改进"）：
- 头：u32@0 = declared（上界），u32@4 = tag，u32@8 不读不校验。
- base = 12，stride = tag + 8。
- 判据 M：f32@at+12 == 0.0 且 f32@at+28 == 0.0 且 f32@at+44 == 0.0 且 f32@at+60 == 1.0。
- 判据 N：at+64 起可打印 ASCII（0x21..=0x7e，排除空格与反斜杠）到 0x00，
  长度 1..=200。
- 走法：从 12 开始按 stride 步进；`len < off + 64 + 2` 停；
  第 0 条 M/N 不成立 → LayoutUndetermined(failed_at=0)；中间不成立 → 停在那里。
- 尾部不解，只报剩余字节数。

只读，不改任何项目文件。
"""
import struct

BASE = 12
MATRIX_BYTES = 64
MAX_NAME = 200
KNOWN_TAGS = [753, 749, 605, 592, 596, 601, 324, 957]


class LayoutUndetermined(Exception):
    def __init__(self, failed_at):
        super().__init__(f"LayoutUndetermined at {failed_at}")
        self.failed_at = failed_at


def u32_at(raw, off):
    if off + 4 > len(raw):
        return None
    return struct.unpack_from("<I", raw, off)[0]


def f32_at(raw, off):
    if off + 4 > len(raw):
        return None
    return struct.unpack_from("<f", raw, off)[0]


def satisfies_m(raw, at):
    return (
        f32_at(raw, at + 12) == 0.0
        and f32_at(raw, at + 28) == 0.0
        and f32_at(raw, at + 44) == 0.0
        and f32_at(raw, at + 60) == 1.0
    )


def read_name_at(raw, at):
    start = at + MATRIX_BYTES
    end = start
    while True:
        if end >= len(raw):
            return None
        c = raw[end]
        if c == 0:
            break
        if not (0x20 <= c <= 0x7E) or c == 0x20 or c == 0x5C:
            return None
        end += 1
        if end - start > MAX_NAME:
            return None
    if end == start:
        return None
    return raw[start:end].decode("ascii")


def parse_scene(raw):
    """返回 SceneGrid 字典；TooShort/UnknownVersion/LayoutUndetermined 以异常/错误码表示。

    与 Rust 的差别只在错误载体：这里返回 (kind, grid_or_none)。
      kind in {"ok", "too_short", "unknown_version", "layout_undetermined"}
    """
    if len(raw) < BASE:
        return "too_short", None
    declared = u32_at(raw, 0)
    tag = u32_at(raw, 4)
    if tag not in KNOWN_TAGS:
        return "unknown_version", None
    stride = tag + 8

    instances = []
    offset = BASE
    failed_at = None
    while True:
        if len(raw) < offset + MATRIX_BYTES + 2:
            break
        idx = len(instances)
        if not satisfies_m(raw, offset):
            if idx == 0:
                return "layout_undetermined", {"failed_at": 0}
            failed_at = idx
            break
        name = read_name_at(raw, offset)
        if name is None:
            if idx == 0:
                return "layout_undetermined", {"failed_at": 0}
            failed_at = idx
            break
        m = struct.unpack_from("<16f", raw, offset)
        instances.append(
            {
                "name": name,
                "m": m,
                "pos": (m[12], m[13], m[14]),
            }
        )
        offset += stride

    consumed = BASE + stride * len(instances)
    tail = max(0, len(raw) - consumed)
    return "ok", {
        "declared": declared,
        "tag": tag,
        "stride": stride,
        "instances": instances,
        "tail_bytes": tail,
        "has_tail": tail > 0,
        "understated": len(instances) > declared,
    }


def is_empty_grid(raw):
    return len(raw) == 4 and u32_at(raw, 0) == 0
