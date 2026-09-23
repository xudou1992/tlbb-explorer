import re, collections, idautils, idc

out = []
w = out.append

allstr = []
for st in idautils.Strings():
    allstr.append(str(st))
blob_txt = '\n'.join(allstr)

w('total_strings %d' % len(allstr))
w('')
w('==== engine/middleware fingerprints ====')
for pat in ['OGR', 'ogre', 'OGRE', 'Cegui', 'CEGUI', 'FreeType', 'freetype', 'FMOD', 'fmod',
            'Wwise', 'wwise', 'AkSoundEngine', 'LZMA', 'lzma', 'Deflate', 'Houdini',
            'OgreMain', 'RenderSys', 'Direct3D9', 'D3D11', 'DXGI', 'PhysX', 'physx', 'Bullet',
            'Havok', 'Recast', 'Detour', 'Lua', 'luajit', 'yasio', 'yasli', 'protobuf', 'flatbuf',
            'SQLite', 'sqlite', 'MySQL', 'my_', 'MySQL', 'sproto', 'TinyXML', 'pugixml',
            'curl', 'libcurl', 'websocket', 'WebSocket', 'Tween', 'Spine', 'cocos', 'Scaleform']:
    hits = [s for s in allstr if pat in s]
    if hits:
        w('[%-12s] %4d  e.g. %s' % (pat, len(hits), ' | '.join(sorted(set(hits))[:4])[:220]))

w('')
w('==== LuaScriptFunc:: exported API sample ====')
lf = sorted({s for s in allstr if s.startswith('LuaScriptFunc::') or s.startswith('LuaGlobal_') or s.startswith('Lua')})
w('count=%d' % len(lf))
for x in lf[:120]:
    w('  ' + x)

w('')
w('==== server / protocol endpoints ====')
for x in sorted({s for s in allstr if re.search(r'(10\.|192\.168|\.(cn|com|net)):?\d*', s) and len(s) < 60 and re.search(r'[A-Za-z0-9]\.\d{1,3}\.\d{1,3}', s)}):
    w('  ' + x)
for x in sorted({s for s in allstr if re.search(r'\.(changyou|sohu|qcloud|tencentcloudapi)\.', s) and len(s) < 80})[:60]:
    w('  ' + x)

w('')
w('==== game-system class names from global namespace ====')
rt = [str(s)[4:] for s in idautils.Strings() if str(s).startswith('.?AV') and not str(s)[4:5] in ('$0',)]
names = []
for r in rt:
    m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)@@$', r)
    if m:
        names.append(m.group(1))
w('global-ns classes: %d' % len(names))

# cluster by suffix/prefix conventions
pref = collections.Counter()
for n in names:
    mm = re.match(r'^(I)([A-Z])', n)
    if mm:
        pref['interface:I*'] += 1
    for p in ['Scene', 'Render', 'Lua', 'Sound', 'Tex', 'Mater', 'Anim', 'Parti', 'Shadow', 'Light',
              'Mesh', 'Entity', 'Node', 'Resource', 'Loader', 'Packet', 'Socket', 'Net', 'UI', 'Effect',
              'Collider', 'Emitter', 'Affector', 'Billboard', 'Terrain', 'Camera', 'Stream', 'File',
              'Package', 'Update', 'Download', 'Shader', 'Buffer', 'Thread', 'Task', 'Async', 'Cache']:
        if p.lower() in n.lower():
            pref[p] += 1
for k, v in pref.most_common(45):
    w('  %6d  %s' % (v, k))

open(r'D:\TLGL\.scratch\fp_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->fp_out.txt')
