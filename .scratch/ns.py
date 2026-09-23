import re, collections, idautils, idc

raw = []
for st in idautils.Strings():
    x = str(st)
    if x.startswith('.?AV'):
        raw.append(x[4:])

# MSVC RTTI: .?AV<Name>@<Namespace>@@  -- take the leading identifier only (skip templates)
cls = []
for r in raw:
    if r.startswith('$'):
        continue
    m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)@', r)
    if not m:
        continue
    name = m.group(1)
    rest = r[m.end():]
    ns = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)@', rest)
    cls.append((ns.group(1) if ns else '<global>', name))

cnt = collections.Counter(ns for ns, _ in cls)
out = ['class_with_ns %d, distinct namespaces %d' % (len(cls), len(cnt))]
for ns, n in cnt.most_common(60):
    names = sorted({c for k, c in cls if k == ns})
    out.append('')
    out.append('########## namespace %s  (%d classes) ##########' % (ns, n))
    out.append(', '.join(names[:90]))

open(r'D:\TLGL\.scratch\ns_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->ns_out.txt', len(cnt), 'namespaces')
