import struct, sqlite3, sys, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
def sdbm(b):
    h = 0
    for x in b: h = (x + (h<<6) + (h<<16) - h) & 0xffffffff
    return h
raw = open('D:/TLGL/.scratch/out/tree/global.jstr','rb').read()
n4 = len(raw)//4
u = struct.unpack_from('<%dI' % n4, raw, 0)
# descriptors from offset 24 (u index 6): (len, hash) pairs
cands = []
S = 0
N = 0
m = 6
while 8*m + 4 <= len(raw):
    L = u[m]
    if L == 0 or L > 4096: break
    S += L; N += 1; m += 2
    if 24 + 8*N + S == len(raw):
        cands.append((N, 24+8*N))
    if len(cands) > 3: break
print('self-consistent endpoints:', cands)
if cands:
    N, CHARSOFF = cands[0]
    arr = u[6:6+2*N]
    lens, hashes = arr[0::2], arr[1::2]
    p = CHARSOFF
    strings = []
    for L in lens:
        strings.append(raw[p:p+L].decode('utf-8','replace')); p += L
    print(f'N={N} chars@{CHARSOFF} decoded={len(strings)} ends={p==len(raw)}')
    print('first 20 strings:', strings[:20])
    ext = collections.Counter(s.lower().rsplit('.',1)[-1] for s in strings if '.' in s)
    print('ext top:', ext.most_common(10))
    c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
    hiset = {int(h,16)>>32 for (h,) in c.execute('select hash from resources')}
    anonet = {int(h,16)>>32 for (h,) in c.execute("select hash from resources where type='texture' and named=0")}
    m1 = sum(1 for s in strings if s and sdbm(s.lower().encode()) in hiset)
    m2 = sum(1 for x in hashes[:len(strings)] if x in hiset)
    m3 = sum(1 for x in hashes[:len(strings)] if x in anonet)
    print(f'sdbm(lower(s)) ∈ pak high32: {m1}/{len(strings)}')
    print(f'stored hash ∈ pak high32: {m2}/{len(strings)}  ∈ anon tex: {m3}')
