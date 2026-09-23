import re, collections, idautils, idc, ida_bytes, ida_segment, math

out = []
w = out.append

# ---------- entropy profile ----------
s = idc.get_segm_by_name('.text')
sg = ida_segment.getseg(s)
st, en = sg.start_ea, sg.end_ea
w('=== .text 0x%X-0x%X : entropy per 64K window / func count ===')
a = st
while a < en:
    take = min(0x10000, en - a)
    b = ida_bytes.get_bytes(a, take) or b''
    cnt = collections.Counter(b)
    ent = -sum((v / len(b)) * math.log2(v / len(b)) for v in cnt.values()) if b else 0
    nf = sum(1 for _ in idautils.Functions(a, a + take))
    w('  %016X ent=%.2f funcs=%d' % (a, ent, nf))
    a += take

# ---------- source path / module tree ----------
strs = [(x.ea, str(x)) for x in idautils.Strings()]
w('')
w('=== total strings: %d ===' % len(strs))

paths = sorted({t for _, t in strs if re.search(r'\.(cpp|c|h|hpp)$', t, re.I) and len(t) < 200})
w('')
w('=== source-file path strings: %d ===' % len(paths))
for p in paths[:400]:
    w('  ' + p)

# namespaces inferred from those paths
w('')
w('=== path directory histogram ===')
c = collections.Counter()
for p in paths:
    d = p.replace('\\', '/').rsplit('/', 1)[0] if '/' in p.replace('\\', '/') else '<none>'
    c[d] += 1
for k, v in c.most_common(80):
    w('%6d  %s' % (v, k))

open(r'D:\TLGL\.scratch\v2_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->v2_out.txt lines=%d paths=%d' % (len(out), len(paths)))
