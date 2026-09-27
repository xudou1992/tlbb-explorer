"""Read-only blind-spot probe helpers for resources.db.

NO writes to D:\\TLGL anywhere. Only opens paks 'rb' and db in mode=ro.
"""
import os
import re
import sqlite3
import struct
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from pakdec import parse_index, dec  # noqa: E402
from snappy import snappy_decode, SnappyError  # noqa: E402

DB = r'D:\TLGL\.scratch\resources.db'
GAME = r'D:\TLGL'
PAKS = ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']


def db():
    return sqlite3.connect('file:' + DB.replace('\\', '/') + '?mode=ro', uri=True)


class Store:
    """Lazily-opened read-only pak handles + hash->record index."""

    def __init__(self):
        self.files = {}
        self.recs = {}
        self._loaded = False

    def load(self):
        if self._loaded:
            return
        for p in PAKS:
            f, recs = parse_index(os.path.join(GAME, p))
            self.files[p] = f
            for r in recs:
                self.recs['%016x' % r['hash']] = (p, r)
        self._loaded = True

    def fetch(self, h):
        """Return plaintext bytes for resource hash h, or (None, reason)."""
        self.load()
        hit = self.recs.get(h)
        if hit is None:
            return None, 'not-in-index'
        pname, rec = hit
        f = self.files[pname]
        f.seek(rec['off'])
        raw = f.read(rec['size'])
        if len(raw) < rec['size']:
            return None, 'short-read'
        d = dec(rec['hash'], rec['size'], raw) if (rec['flags'] & 4) else raw
        if rec['flags'] & 1:  # inline path manifest prefix
            pl = d[0]
            d = d[1 + pl + 16:]
        if rec['meth'] == 0:
            return d, 'stored'
        if rec['meth'] == 51:
            try:
                out, _c = snappy_decode(d, rec['osize'])
                return out, 'snappy'
            except SnappyError as e:
                try:
                    out, _c = snappy_decode(d)
                    return out, 'snappy-noexp'
                except SnappyError as e2:
                    return None, 'snappy-fail:%s' % e2
        return None, 'meth=%d' % rec['meth']


PRINTABLE = re.compile(rb'[\x20-\x7e]{4,}')


def strings(b, minlen=4, limit=40):
    return [s.decode('latin1') for s in PRINTABLE.findall(b)[:limit]]


def hexhead(b, n=48):
    return b[:n].hex(' ')


def histogram(vals, top=12):
    from collections import Counter
    return Counter(vals).most_common(top)
