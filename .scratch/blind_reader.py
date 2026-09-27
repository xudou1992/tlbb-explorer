"""Read-only direct reader: fetch plaintext resource bytes using resources.db (pak, offset, stored)
plus pakdec decryption and raw-snappy decompression.  Never writes."""
import sys, os, re, struct, sqlite3, binascii
sys.path.insert(0, r'D:\TLGL\.scratch')
from pakdec import dec
from snappy import snappy_decode, SnappyError

DB = 'D:/TLGL/.scratch/resources.db'
GAME = 'D:/TLGL/'
COLS = 'hash,pak,offset,stored,original,flags,method,filecrc,type,subtype,ext,props,name,dir,path'


def conn():
    c = sqlite3.connect('file:' + DB + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    return c


class Reader:
    def __init__(self):
        self.f = {}

    def raw(self, pak, off, stored):
        fh = self.f.get(pak)
        if fh is None:
            fh = self.f[pak] = open(GAME + pak + '.pak', 'rb')
        fh.seek(off)
        b = fh.read(stored)
        return b if len(b) == stored else None

    def get(self, row):
        """-> (bytes|None, reason)"""
        raw = self.raw(row['pak'], row['offset'], row['stored'])
        if raw is None:
            return None, 'short-read'
        if row['flags'] & 4:
            buf = dec(int(row['hash'], 16), row['stored'], raw)
        else:
            buf = raw
        if binascii.crc32(raw) & 0xFFFFFFFF != (row['filecrc'] & 0xFFFFFFFF):
            reason = 'crc-mISMATCH'
        else:
            reason = ''
        if row['flags'] & 1:
            pl = buf[0]
            buf = buf[1 + pl + 16:]
        m = row['method']
        if m == 0:
            return buf, ('stored' + reason)
        if m == 51:
            try:
                out, _ = snappy_decode(buf, row['original'])
                return out, ('snappy' + reason)
            except SnappyError as e:
                return None, ('snappy-fail:%s%s' % (e, reason))
        return None, ('method=%d%s' % (m, reason))


STR = re.compile(rb'[\x20-\x7e]{4,}')


def strings(b, n=30):
    return [s.decode('latin1') for s in STR.findall(b)[:n]]


def u32le(b, n=8):
    k = min(n, len(b) // 4)
    return list(struct.unpack('<%dI' % k, b[:4 * k])) if k else []


def hist(vals, n=10):
    from collections import Counter
    return Counter(vals).most_common(n)
