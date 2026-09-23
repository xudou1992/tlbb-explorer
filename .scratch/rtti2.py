import ida_name, idautils, re, collections, json

names = [ida_name.get_name(n) for n in idautils.Names()]
rtti = [n[4:] for n in names if n.startswith('.?AV')]


def clean(n):
    n = re.sub(r'\?[^@]*', '', n)
    return n


def ns(n):
    parts = [p for p in n.split('@') if p]
    return parts[-2] if len(parts) >= 2 else '<global>'


out = []
out.append('names_total %d' % len(names))
out.append('rtti_total %d' % len(rtti))
out.append('rtti_named_sample %s' % json.dumps(rtti[:8]))

c = collections.Counter(ns(n) for n in rtti)
out.append('--- namespace histogram ---')
for k, v in c.most_common(70):
    out.append('%6d  %s' % (v, k))

with open(r'D:\TLGL\.scratch\rtti_out.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))
print('WROTE', len(out), 'lines')
