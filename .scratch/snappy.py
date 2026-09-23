"""Raw Snappy block format decoder (no framing chunk)."""


class SnappyError(Exception):
    pass


def _read_varint(buf, pos):
    val = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, pos
        shift += 7
        if shift > 35:
            raise SnappyError('varint too long')


def snappy_decode(src, expected_len=None):
    """Decode a raw snappy block; returns (out, consumed)."""
    ulen, p = _read_varint(src, 0)
    if expected_len is not None and ulen != expected_len:
        raise SnappyError('declared %d != expected %d' % (ulen, expected_len))
    out = bytearray()
    n = len(src)
    while p < n:
        tag = src[p]
        p += 1
        t = tag & 3
        if t == 0:                       # literal
            ln = tag >> 2
            if ln < 60:
                ln += 1
            else:
                extra = ln - 59
                if p + extra > n:
                    raise SnappyError('truncated literal len')
                ln = 1 + int.from_bytes(src[p:p + extra], 'little')
                p += extra
            if p + ln > n:
                raise SnappyError('truncated literal')
            out += src[p:p + ln]
            p += ln
            continue
        if t == 1:                       # copy, 1-byte offset
            ln = 4 + ((tag >> 2) & 7)
            off = ((tag >> 5) << 8) | src[p]
            p += 1
        elif t == 2:                     # copy, 2-byte offset
            ln = 1 + (tag >> 2)
            off = int.from_bytes(src[p:p + 2], 'little')
            p += 2
        else:                            # copy, 4-byte offset
            ln = 1 + (tag >> 2)
            off = int.from_bytes(src[p:p + 4], 'little')
            p += 4
        if off == 0 or off > len(out):
            raise SnappyError('bad offset %d at %d' % (off, p))
        start = len(out) - off
        for i in range(ln):
            out.append(out[start + i])
    if len(out) != ulen:
        raise SnappyError('output %d != declared %d' % (len(out), ulen))
    return bytes(out), p
