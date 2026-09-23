import re, collections, idautils

txts = sorted({str(s) for s in idautils.Strings()})
out = []

paths = [t for t in txts if re.search(r'(\.cpp|\.c|\.h|\.hpp)$', t, re.I) and len(t) < 220]
internal = [p for p in paths if re.search(r'Engine_Gfx|Fantasy|TLBB|W1351|RenderCore|\\Code\\|Code_Inner', p, re.I)]

out.append('all source paths: %d ; internal(project) paths: %d' % (len(paths), len(internal)))
out.append('')
out.append('=== internal module directories (normalized) ===')
d = collections.Counter()
for p in internal:
    q = p.replace('\\', '/')
    q = re.sub(r'^[A-Za-z]:/(W1351|TLBB_OB|\.\.\.)/', '', q)
    q = re.sub(r'^(Branches/Development/Code/DevEnv|Code_Inner/DevEnv)/', '3rdparty/', q)
    q = re.sub(r'/[^/]*$', '', q)
    d[q] += 1
for k, v in d.most_common(60):
    out.append('%5d  %s' % (v, k))

out.append('')
out.append('=== every internal path verbatim ===')
for p in sorted(set(internal)):
    out.append('  ' + p)

open(r'D:\TLGL\.scratch\tree_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->tree_out.txt internal=%d' % len(internal))
