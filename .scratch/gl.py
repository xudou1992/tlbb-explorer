import re, collections, idautils

gl = []
for st in idautils.Strings():
    x = str(st)
    if not x.startswith('.?AV'):
        continue
    r = x[4:]
    m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)@@', r)   # no namespace at all
    if m:
        gl.append(m.group(1))
        continue
    m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)@([A-Za-z_][A-Za-z0-9_]*)@@', r)  # one namespace
    if m and m.group(2) in ('', ):
        pass

gl = sorted(set(gl))
out = ['global-ns concrete classes: %d' % len(gl)]

buckets = collections.defaultdict(list)
RULES = [
    ('lua/script', r'(?i)lua|script'),
    ('net/socket/proto', r'(?i)socket|packet|protocol|connect|http|download|session|crypt|gateway|server'),
    ('scene/world/gameplay', r'(?i)scene|world|player|character|npc|monster|role|skill|buff|item|quest|move|path|team|actor|game|entity|ai\b|collision|obstacle'),
    ('render/gfx', r'(?i)render|gfx|texture|shader|buffer|vertex|blend|depth|viewport|sampler|device|dx11|d3d|swap|light|shadow|postprocess|bloom|pipeline|pass'),
    ('ui', r'(?i)^ui|widget|window|button|edit|font|text|layout|image|anim'),
    ('resource/fs/pak', r'(?i)resource|package|file|archive|stream|loader|manager|cache|pak|storage'),
    ('audio', r'(?i)sound|audio|mp3|ogg|wave|volume|microphone'),
    ('anim/fx', r'(?i)anim|effect|particle|emitter|key|spline|tween|bones|movie|gif|video'),
    ('anticheat/security', r'(?i)nep|yidun|protect|guard|verify|signature|machine|token|encrypt|secure|hook|detect'),
    ('platform/win', r'(?i)win32|platform|app|crash|dump|registry|hotkey|cursor|ime|monitor|network'),
    ('math/geom', r'(?i)vec|matrix|quat|box|sphere|rect|plane|geom|math|color|transform|coord'),
    ('task/thread', r'(?i)task|thread|job|fiber|queue|async|pool|schedul'),
]
assigned = set()
for c in gl:
    for name, pat in RULES:
        if re.search(pat, c):
            buckets[name].append(c)
            assigned.add(c)
            break
for k in sorted(buckets, key=lambda x: -len(buckets[x])):
    out.append('')
    out.append('### %s (%d)' % (k, len(buckets[k])))
    out.append('  ' + ', '.join(sorted(buckets[k])[:80]))
rest = [c for c in gl if c not in assigned]
out.append('')
out.append('### unclassified (%d)' % len(rest))
out.append('  ' + ', '.join(rest[:150]))

open(r'D:\TLGL\.scratch\gl_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->gl_out.txt', len(gl))
