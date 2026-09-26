import struct, sqlite3, sys, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
def sdbm(b):
    h = 0
    for x in b: h = (x + (h<<6) + (h<<16) - h) & 0xffffffff
    return h
raw = open('D:/TLGL/.scratch/out/tree/global.jstr','rb').read()
print('magic', raw[:4], 'u32@4', struct.unpack_from('<I',raw,4)[0], 'u32@8', raw[8:12],
      'u32@12', struct.unpack_from('<I',raw,12)[0], 'u32@16', struct.unpack_from('<I',raw,16)[0])
CNT = struct.unpack_from('<I', raw, 20)[0]
print('count candidate:', CNT)
arr = struct.unpack_from('<%dI' % (2*CNT), raw, 24)
lens, hashes = arr[0::2], arr[1::2]
CHARS = 24 + 8*CNT
S = sum(lens)
print(f'chars@{CHARS} chars_len={len(raw)-CHARS} sum(len)={S} diff={len(raw)-CHARS-S}')
p = CHARS
strings = []
for L in lens:
    strings.append(raw[p:p+L].decode('utf-8','replace')); p += L
print('decoded', len(strings), 'exact end:', p == len(raw))
print('first 10:', strings[:10])
ext = collections.Counter(s.lower().rsplit('.',1)[-1] for s in strings if '.' in s)
print('ext top10:', ext.most_common(10))
c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
hiset = {int(h,16)>>32 for (h,) in c.execute('select hash from resources')}
anon = {int(h,16)>>32 for (h,) in c.execute("select hash from resources where type='texture' and named=0")}
m1 = sum(1 for s in strings if s and sdbm(s.lower().encode()) in hiset)
m2 = sum(1 for x in hashes if x in hiset)
m3 = sum(1 for x in hashes if x in anon)
m4 = sum(1 for s in strings if s and sdbm(s.lower().encode()) in anon)
print(f'[A] sdbm(lower(s)) ∈ ALL pak high32: {m1}/{len(strings)}')
print(f'[B] sdbm(lower(s)) ∈ ANON tex high32: {m4}/{len(strings)}')
print(f'[C] stored hash ∈ ALL pak high32: {m2}/{len(strings)}')
print(f'[D] stored hash ∈ ANON tex high32: {m3}/{len(strings)}')
