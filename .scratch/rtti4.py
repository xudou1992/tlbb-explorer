import re, collections
import idautils, idc, ida_name

lines = []
raw = []
for s in idautils.Strings():
    s = str(s)
    if s.startswith('.?AV') or s.startswith('.?AU'):
        raw.append(s)


def manual(t):
    t = re.sub(r'^\.\?A[UV]', '', t)
    t = re.sub(r'@@+$', '', t)
    return t.replace('@', '::')


man = [manual(r) for r in raw]
lines.append('rtti_total %d' % len(man))

# namespace = the token right before the class token
c = collections.Counter()
for m in man:
    parts = [p for p in m.split('::') if p and not p.startswith('?')]
    if len(parts) >= 2:
        c[parts[-2]] += 1
    elif parts:
        c['<global>'] += 1
lines.append('--- RTTI namespace histogram ---')
for k, v in c.most_common(70):
    lines.append('%6d  %s' % (v, k))

lines.append('--- per-namespace class lists (depth<=2, readable) ---')
by = collections.defaultdict(set)
for m in man:
    if '::' in m and m.count('::') <= 2 and '?' not in m:
        parts = m.split('::')
        if len(parts) == 2:
            by[parts[0]].add(parts[1])
        else:
            by['<global>'].add(parts[-1])
for ns in sorted(by, key=lambda k: -len(by[k]))[:30]:
    lines.append('[%s] n=%d :: %s' % (ns, len(by[ns]), ', '.join(sorted(by[ns])[:30])))

open(r'D:\TLGL\.scratch\rtti4_out.txt', 'w', encoding='utf-8').write('\n'.join(lines))
print('OK', len(lines))
