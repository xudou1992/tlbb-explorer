"""JBPU (.pu) — the particle-effect definition container.

Same interning scheme as BinaryConfigFile: a (len, hash) table then a packed char pool.

    [0]  'JBPU'
    [4]  u32 count
    [8]  count * (u32 len, u32 hash)
    ...  packed strings
    ...  parameter blob

The strings are the interesting part: an effect names its material file, its blend mode,
its renderer, its emitter shape, its updaters and its dynamic parameters, e.g.

    w1351_scene_wudangshan_smoke01 / scene / smoke_01 / w1351_smoke_h005.mtl /
    add / Billboard / Box / dyn_random / Colour / Scale / dyn_curved_linear / Jet /
    TextureRotator

So the effect -> material -> texture chain is recoverable from the .pu itself, which is
what the .mtl string table gave for characters and props.
"""
import collections
import os
import re
import struct

from jbcf import sdecode

# bytes.translate wants a 256-byte table, not a dict
SEP = bytes((ord('/') if 0x1c <= c < 0x20 else c) for c in range(256))

BLEND = ('add', 'alpha', 'blend', 'multiply', 'screen', 'none', 'subtract')
# Exact class names, not substrings: layer names such as mesh_canying01 or Point would
# otherwise be misread as renderer / emitter classes.
RENDERER = {'billboard', 'ribbontrail', 'meshsurface', 'entity', 'trail', 'plane',
            'pointcloud', 'decal', 'projector'}
EMITTER = {'box', 'sphere', 'jet', 'point', 'ring', 'cylinder', 'circle', 'line',
           'polar', 'null', 'boxedge'}
UPDATER = ('rotator', 'animator', 'affector', 'vortex', 'force', 'gravity', 'fade',
           'scale', 'colour', 'color', 'speed')
MATERIAL_RE = re.compile(r'\.(mtl|mesh|ske|ani|tga|dds|png|pu)$', re.I)


def parse(raw):
    if raw[:4] != b'JBPU' or len(raw) < 8:
        raise ValueError('not jbpu')
    cnt = struct.unpack_from('<I', raw, 4)[0]
    if not 0 < cnt < 4096 or 8 + 8 * cnt > len(raw):
        raise ValueError('count %d' % cnt)
    tab = struct.unpack_from('<%dI' % (2 * cnt), raw, 8)
    pairs = [(tab[i], tab[i + 1]) for i in range(0, 2 * cnt, 2)]
    pool = 8 + 8 * cnt
    total = sum(l for l, _ in pairs)
    if pool + total > len(raw):
        raise ValueError('pool overflow')
    out, p = [], pool
    for ln, hv in pairs:
        s = raw[p:p + ln]
        # 0x1C..0x1F are legal name separators in this container ("point\x1f_03");
        # any other control byte means we are looking at binary, not text.
        if any(c < 9 or 14 <= c < 0x1c for c in s):
            raise ValueError('chars')
        out.append(sdecode(s.translate(SEP)))
        p += ln
    return out, raw[p:]


def classify(names):
    """Bucket the interned strings by what they do in the particle system."""
    role = {'name': '', 'group': '', 'label': '', 'material': [], 'texture': [],
            'mesh': [], 'blend': [], 'renderer': [], 'emitter': [], 'updater': [],
            'dynamic': [], 'other': []}
    for i, n in enumerate(names):
        low = n.lower()
        if MATERIAL_RE.search(low):
            if low.endswith('.mtl'):
                role['material'].append(n)
            elif low.endswith(('.tga', '.dds', '.png')):
                role['texture'].append(n)
            else:
                role['mesh'].append(n)
            continue
        if low.startswith('dyn_'):
            role['dynamic'].append(n)
        elif low in RENDERER:
            role['renderer'].append(n)
        elif low in EMITTER:
            role['emitter'].append(n)
        elif any(low.startswith(b) for b in BLEND):
            role['blend'].append(n)
        elif any(u in low for u in UPDATER):
            role['updater'].append(n)
        elif i == 0:
            role['name'] = n
        elif i == 1:
            role['group'] = n
        elif i == 2:
            role['label'] = n
        else:
            role['other'].append(n)
    return role


def params(blob):
    """Floats in the parameter region, by local density — enough to show scale/colour/time.

    Deliberately not claimed as named fields: the field grammar is the next step.
    """
    n = len(blob) // 4
    if n < 2:
        return []
    vals = struct.unpack('<%df' % n, blob[:n * 4])
    return [round(v, 4) for v in vals if 1e-4 < abs(v) < 1e5]


def census(paths=None, limit=None):
    import sqlite3
    con = sqlite3.connect('file:%s?mode=ro' % os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'resources.db'), uri=True)
    idx = {}
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out', 'all')
    for pak in os.listdir(root):
        d = os.path.join(root, pak)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                idx[fn[:16]] = os.path.join(d, fn)
    ok = err = 0
    roles = collections.Counter()
    has_mtl = 0
    nstr = collections.Counter()
    ex = []
    for h, p in con.execute("select hash, path from resources where type='JBPU'"):
        f = idx.get(h)
        if not f:
            continue
        try:
            names, blob = parse(open(f, 'rb').read())
        except ValueError as e:
            err += 1
            roles['ERR:' + str(e).split()[0] if 'not' not in str(e) else 'ERR:magic'] += 1
            continue
        ok += 1
        r = classify(names)
        nstr[len(names)] += 1
        for k in ('material', 'texture', 'blend', 'renderer', 'emitter', 'updater',
                  'dynamic', 'other'):
            if r[k]:
                roles[k] += 1
        if r['material']:
            has_mtl += 1
        if len(ex) < 4 and r['material']:
            ex.append((p, names, len(blob)))
    print('JBPU parsed %d, failed %d' % (ok, err))
    print('roles present: %s' % roles.most_common())
    print('effects naming a material: %d / %d (%.1f%%)' % (has_mtl, ok, 100.0 * has_mtl / ok))
    print('names per effect: %s' % nstr.most_common(8))
    for p, names, bl in ex:
        print('  %s  (%d strings, %d bytes of params)' % (p, len(names), bl))
        print('     %s' % names)
    return ok, err


if __name__ == '__main__':
    census()
