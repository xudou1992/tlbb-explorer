import sys, sqlite3, struct
sys.path.insert(0, r'D:\TLGL\.scratch')
from pakdec import dec
from snappy import snappy_decode, SnappyError

DB = 'D:/TLGL/.scratch/resources.db'
G = 'D:/TLGL/'

c = sqlite3.connect('file:' + DB + '?mode=ro', uri=True)
files = {}

def read(h):
    row = c.execute('select hash,pak,offset,stored,original,flags,method,ver,occupied,type,subtype,ext from resources where hash=?', (h,)).fetchone()
    if not row:
        return None, 'no-row', row
    h, pak, off, stored, orig, flags, method, ver, occ, typ, sub, ext = row
    f = files.get(pak)
    if f is None:
        f = files[pak] = open(G + pak + '.pak', 'rb')
    f.seek(off)
    raw = f.read(stored)
    if len(raw) < stored:
        return None, 'short', row
    key = int(h, 16)
    d = dec(key, stored, raw) if (flags & 4) else raw
    man = None
    if flags & 1:
        pl = d[0]
        man = d[1:1+pl]
        d = d[1+pl+16:]
    if method == 0:
        return d, 'stored', row
    if method == 51:
        try:
            out, _ = snappy_decode(d, orig)
            return out, 'snappy', row
        except SnappyError as e:
            try:
                out, _ = snappy_decode(d)
                return out, 'snappy-noexp', row
            except SnappyError as e2:
                return None, 'snfail:' + str(e2), row
    return None, 'method=%d' % method, row

if __name__ == '__main__':
    for h in ['000e124a5c235113', '000ecb1beb9cb2ee', '00008fcbcbe6856f']:
        b, why, row = read(h)
        print(h, why, len(b) if b else None, row[1:8] if row else None)
        if b:
            print('   ', b[:48].hex(' '))
            print('   ', b[:40])
