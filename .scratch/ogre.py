import re, collections, idautils

txts = sorted({str(s) for s in idautils.Strings()})
out = []

hits = [t for t in txts if re.search(r'ogre', t, re.I)]
out.append('strings containing "ogre": %d' % len(hits))
for h in hits[:40]:
    out.append('  ' + h[:160])

out.append('')
out.append('=== ALL third-party source-path strings (reveal build tree) ===')
paths = sorted({t for t in txts if re.search(r'(\.cpp|\.c|\.h)$', t) and len(t) < 200})
d = collections.Counter()
for p in paths:
    q = p.replace('\\', '/')
    m = re.search(r'([A-Za-z]:)?/?([^<>]*)/(?:src|include|code|Source|third_party|3rdparty|contrib|lib|modules)?/?([^/]*)$', q)
    d[q.rsplit('/', 1)[0] if '/' in q else '<flat>'] += 1
out.append('distinct source paths: %d' % len(paths))
for k, v in d.most_common(70):
    out.append('%5d  %s' % (v, k))

out.append('')
out.append('=== vendor directory roots seen in paths ===')
roots = sorted({p for p in paths if re.match(r'^[A-Za-z]:', p)})
for r in roots[:80]:
    out.append('  ' + r)

open(r'D:\TLGL\.scratch\ogre_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->ogre_out.txt  ogre_hits=%d paths=%d' % (len(hits), len(paths)))
