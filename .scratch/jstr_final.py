import struct, sqlite3, sys, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
def sdbm(b):
    h = 0
    for x in b: h = (x + (h<<6) + (h<<16) - h) & 0xffffffff
    return h
raw = open('D:/TLGL/.scratch/out/tree/global.jstr','rb').read()
CNT = struct.unpack_from('<I', raw, 20)[0]
arr = struct.unpack_from('<%dI' % (2*CNT), raw, 24)
lens, hashes = arr[0::2], arr[1::2]
p = 24 + 8*CNT
strings = []
for L in lens:
    strings.append(raw[p:p+L].decode('utf-8','replace')); p += L + 1
print(f'N={CNT} exact end: {p == len(raw)}')
print('first 8:', strings[:8])
ext = collections.Counter(s.lower().rsplit('.',1)[-1] for s in strings if '.' in s)
print('ext top10:', ext.most_common(10))
c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
hiset = {int(h,16)>>32 for (h,) in c.execute('select hash from resources')}
anon = {int(h,16)>>32 for (h,) in c.execute("select hash from resources where type='texture' and named=0")}
m1 = sum(1 for s in strings if s and sdbm(s.lower().encode()) in hiset)
m4 = sum(1 for s in strings if s and sdbm(s.lower().encode()) in anon)
m2 = sum(1 for x in hashes if x in hiset)
m3 = sum(1 for x in hashes if x in anon)
print(f'[A] sdbm(lower(s)) ∈ ALL pak: {m1}   [B] ∈ anon tex: {m4}')
print(f'[C] stored hash ∈ ALL pak: {m2}   [D] ∈ anon tex: {m3}')
tg = [s for s in strings if s.lower().endswith('.tga')]
print('tga strings:', len(tg), 'sample:', tg[:6])
