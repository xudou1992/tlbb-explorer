import re, sqlite3, struct, sys, collections
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
def sdbm(b):
    h = 0
    for x in b: h = (x + (h<<6) + (h<<16) - h) & 0xffffffff
    return h
raw = open('D:/TLGL/.scratch/out/tree/global.jstr','rb').read()
print('size:', len(raw), 'magic:', raw[:4], 'next u32:', struct.unpack_from('<I', raw, 4)[0])
# try JBCF-style strtab parse starting at various offsets
found = None
for off in (8, 12, 16, 20, 24, 28, 32):
    if off+16 > len(raw): break
    a,b,c,d = struct.unpack_from('<4I', raw, off)
    if d < 5_000_000 and b < len(raw) and off+16+8*d <= len(raw):
        total = sum(struct.unpack_from('<%dI' % d, raw, off+16)[0::2]) if d else 0
        if 0 < total <= len(raw):
            found = (off, b, c, d, total)
            break
print('strtab guess:', found)
if found:
    off, size, flag, cnt = found
    desc = off+16
    arr = struct.unpack_from('<%dI' % (2*cnt), raw, desc)
    lens, hashes = arr[0::2], arr[1::2]
    chars = desc + 8*cnt
    print(f'count={cnt} chars@{chars} sum_len={sum(lens)} file_left={len(raw)-chars}')
    p = chars; strings = []
    for L in lens:
        strings.append(raw[p:p+L].decode('utf-8', 'replace')); p += L
    print('decoded:', len(strings), 'ends exactly:', p==len(raw))
    print('samples:', strings[:6])
    ext = collections.Counter(s.rsplit('.',1)[-1].lower() for s in strings if '.' in s.rsplit('/',1)[-1])
    print('ext top10:', ext.most_common(10))
    tg = [s for s in strings if s.lower().endswith('.tga')]
    print('tga strings:', len(tg), 'sample:', tg[:5])
    # do the string hashes match pak high32 via sdbm of the string itself?
    c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
    hiset = {int(h,16)>>32 for (h,) in c.execute('select hash from resources')}
    hit = 0; tried = 0
    for s in strings[:60000]:
        if not s: continue
        tried += 1
        if sdbm(s.lower().encode()) in hiset: hit += 1
    print(f'sdbm(lower(s)) hits pak high32: {hit}/{tried}')
    # do the STORED per-string hashes match pak high32 directly?
    sh = [hashes[i] for i in range(min(cnt, 60000))]
    m = sum(1 for x in sh if x in hiset)
    print(f'stored per-string hash ∩ pak high32: {m}/{len(sh)}')
