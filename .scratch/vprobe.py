import re, idautils, idc, ida_bytes

pats = [
    (r'G:\\Work', 'work tree'),
    (r'Junlib', 'junlib'),
    (r'Skottie|SkCanvas|SkSurface|SkImage', 'skia'),
    (r'vorbis|ogg/codec|ogg_stream', 'ogg/vorbis'),
    (r'Wwise|AkSoundEngine|AK::|AKSI_', 'wwise'),
    (r'PhysX|PxPhysics|NpScene|PxScene', 'physx'),
    (r'FMOD|fmod_', 'fmod'),
    (r'Houdini|houdini', 'houdini'),
    (r'[Ff]antasy', 'fantasy'),
    (r'\.lua\b', 'lua files'),
    (r'\.gfx\b|\.mesh\b|\.skeleton\b|\.material\b|\.effect\b', 'engine assets'),
    (r'Scaleform|GFScaleform', 'scaleform'),
    (r'Middleware|middleware', 'middleware'),
    (r'\\Include\\|\\Source\\|\\Code\\|\\3rd|\\ThirdParty|\\contrib', 'build tree dirs'),
    (r'^[A-Z]:\\', 'absolute paths'),
]

out = []
hits_all = {}
for st in idautils.Strings():
    t = str(st)
    for p, lab in pats:
        if re.search(p, t):
            hits_all.setdefault(lab, []).append(t)

for p, lab in pats:
    hs = sorted(set(hits_all.get(lab, [])))
    out.append('')
    out.append('==== %s (%s): %d hits ====' % (lab, p, len(hs)))
    for h in hs[:35]:
        out.append('  ' + h[:170])

open(r'D:\TLGL\.scratch\vp_out.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('WROTE ->vp_out.txt')
