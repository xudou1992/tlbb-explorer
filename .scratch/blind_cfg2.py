import sys, re, struct, collections
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings, u32le

R = Reader()
c = conn()
row = c.execute("select * from resources where hash='4b761249ad5d605c'").fetchone()
b, why = R.get(row)
print('ResourcePath.cfg', why, len(b), 'stored', row['stored'], 'props', row['props'])
print('hex[0:128]', b[:128].hex(' '))
print('ascii[0:256]', repr(b[:256]))
print('u32x12', u32le(b, 12))
# JBCF header guess
tag, ver, n1, n2 = struct.unpack('<4sIII', b[:16])
print('tag', tag, 'ver', ver, 'count', n1, n2)
print('tail hex', b[-128:].hex(' '))
print('tail ascii', repr(b[-160:]))
# how many path-like strings
paths = [s for s in strings(b, 200000) if s.endswith('.scene')]
print('.scene paths:', len(paths), paths[:4], paths[-2:])
# search for 16-hex tokens
hexes = collections.Counter(re.findall(rb'[0-9a-f]{16}', b[:200000]))
print('16-hex tokens in first 200KB:', len(hexes), list(hexes.items())[:5])
# do known grid hashes appear as raw u64 LE?
h = '000e124a5c235113'
print('LE bytes of a named grid hash present?', struct.pack('<Q', int(h, 16)) in b, 'BE:', bytes.fromhex(h) in b)
# dump the record area right after header
print('hex[16:160]', b[16:160].hex(' '))
# locate the first path string offset and look at preceding bytes
i = b.find(b'.scene')
seg = b[max(0, i - 400):i + 40]
print('around first .scene @%d:' % i, seg.hex(' '))
print('  ascii:', repr(seg))
