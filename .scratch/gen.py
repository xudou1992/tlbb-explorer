"""Stage 5: grammar-driven path generation (no more blind token guessing).

The client builds resource paths with sprintf templates (found in the binary via IDA):
    %sterrain/%d_%d_%d.tga        %sterrain/%d_%d_%d.Block      %sterrain/%d.TerrainInfo
    settings/_tlbb/AttrContainer/t_AttrType%d.tab               %s/_tlbb/t_job.tab
    collected%d.tga               1_%d_%d.scene                  _%d.ref

The already-recovered `.scene` names give the exact per-map grid coordinates, so instead of
enumerating numbers blindly we instantiate each template with coordinates the map itself proves
it uses.  Every candidate is hash-matched against the pak index; a 64-bit hit names the file.
"""
import collections
import os
import re
import sys
import time

sys.path.insert(0, r'D:\TLGL\.scratch')
from mine2 import batch_hash

HERE = r'D:\TLGL\.scratch'
CH = 400000
MAXLEN = 200
MAPRE = re.compile(r'^(mobile_maps(?:_source)?/[^/]+)/(\d+)_(-?\d+)_(-?\d+)\.scene$')
ROOTS = ('', 'data/', 'logic/', 'ui/', '3d/', 'res/', 'dx11/', 'Pc/', 'settings/', 'mobile_maps/')


def main():
    with open(os.path.join(HERE, 'index.tsv'), encoding='utf-8') as f:
        next(f)
        tset = set(int(l.split('\t', 1)[0], 16) for l in f)
    names = {}
    for fn in ('names_round.tsv', 'dicthits.txt', 'names_new.tsv', 'names.tsv'):
        p = os.path.join(HERE, fn)
        if os.path.isfile(p):
            for l in open(p, encoding='utf-8'):
                if l.startswith('hash\t'):
                    continue
                a = l.rstrip('\n').split('\t')
                if len(a) >= 2 and a[1]:
                    names[a[0]] = a[1]
    print('targets %d, already named %d' % (len(tset), len(names)), flush=True)

    # --- per-map grid coordinates harvested from the recovered scene names -------------
    grids = collections.defaultdict(set)      # mapdir -> {(layer, x, y)}
    for n in names.values():
        m = MAPRE.match(n.replace('\\', '/'))
        if m:
            grids[m.group(1)].add(tuple(int(v) for v in m.groups()[1:]))
    print('maps with a known grid: %d, tiles %d' % (len(grids), sum(len(v) for v in grids.values())), flush=True)

    cands = set()

    def add(p):
        if len(p) <= MAXLEN:
            cands.add(p.encode('gbk', 'replace'))

    # terrain / block / per-tile companions, one candidate set per proven grid cell
    for mapdir, cells in grids.items():
        base, mapname = mapdir.split('/', 1)
        for layer, x, y in cells:
            for yy in {y, abs(y)}:
                for z in range(8):
                    for stem in ('%d_%d_%d' % (x, yy, z), '%d_%d_%d' % (layer, x, yy),
                                 '%d_%d_%d' % (x, yy, layer), '%d_%d' % (x, yy)):
                        for ext in ('tga', 'Block', 'png', 'data', 'bin'):
                            add('%s/terrain/%s.%s' % (mapdir, stem, ext))
                            add('%s/%s.%s' % (mapdir, stem, ext))
                for r in ROOTS:
                    add('%s%s/terrain/%d_%d_%d.tga' % (r, mapname, x, y, 0))
            for z in range(12):
                add('%s/terrain/%d.TerrainInfo' % (mapdir, z))
                add('%s/terrain/%d_%d.TerrainInfo' % (mapdir, x, y))
            for pre in ('collected', '', 'c_'):
                for n in range(64):
                    add('%s/%s%d.tga' % (mapdir, pre, n))
                    add('%s/terrain/%s%d.tga' % (mapdir, pre, n))
        for n in range(12):
            add('%s/%s_%d.ref' % (mapdir, mapname, n))
            add('%s/%s_%d.scene' % (mapdir, mapname, n))
            add('%s/%s_%d.map' % (mapdir, mapname, n))
            add('%s/%s_%d.nav' % (mapdir, mapname, n))
            add('%s/%s_%d.sfl' % (mapdir, mapname, n))
            add('%s/%s.%d.scene' % (mapdir, mapname, n))
        add('%s/%s.scene' % (mapdir, mapname))
        add('%s/%s.map' % (mapdir, mapname))
        add('%s/%s.tga' % (mapdir, mapname))

    # --- engine table files: settings/_tlbb/... with numeric ids -----------------------
    TABL = ['t_buff', 't_buff_functiondef', 't_skill', 't_job', 't_npc_level_fight_attr',
            't_npc_fight_attr_scale', 'RelationForce', 't_AttrContainerDefine', 't_AttrTrans',
            't_AttrConst', 't_AttrContainer', 't_item', 't_item_qual', 't_monster', 't_npc',
            't_task', 't_pet', 't_title', 't_faction', 't_shop', 't_mail', 't_guide']
    for r in ROOTS:
        for t in TABL:
            add('%s_tlbb/%s.tab' % (r, t))
            add('%s_tlbb/AttrContainer/%s.tab' % (r, t))
            add('%ssettings/%s.tab' % (r, t))
    for fam in ('t_AttrType', 't_AttrCondition', 't_AttrAction', 't_AttrFormulaSub',
                't_AttrActionGroup', 't_AttrLuaFormula', 't_AttrContainer', 't_AttrValue'):
        for r in ROOTS:
            for i in range(4000):
                add('%s_tlbb/AttrContainer/%s%d.tab' % (r, fam, i))
    # npc/skill config tables seen as literals in the binary
    for r in ROOTS:
        for t in ('npc/NpcTemplate', 'npc/DoodadTemplate', 'npc/NpcTemplate.tab'):
            add('%ssettings/%s.tab' % (r, t))

    # --- every path-looking literal in the client binary, root-prefixed ----------------
    exe = open(EXEB, 'rb').read() if EXEB else b''
    lit = set()
    for m in re.finditer(rb'[A-Za-z0-9_.\-/\\]{4,120}\.[A-Za-z0-9]{1,6}', exe):
        s = m.group()
        if b'/' in s or b'\\' in s:
            lit.add(s.decode('ascii').replace('\\', '/'))
    print('binary path literals: %d' % len(lit), flush=True)
    for l in lit:
        add(l)
        for r in ROOTS:
            add(r + l)

    print('candidates: %d' % len(cands), flush=True)
    t0 = time.time()
    hits = {}
    cl = list(cands)
    for i in range(0, len(cl), CH):
        chunk = cl[i:i + CH]
        L = min(max(len(t) for t in chunk), MAXLEN)
        for t, h in zip(chunk, batch_hash([t[:L] for t in chunk], L)):
            k = '%016x' % int(h)
            if k in tset and k not in names:
                names[k] = t.decode('gbk', 'replace')
                hits[k] = names[k]
        print('  %d/%d  hits %d (%.0fs)' % (min(i + CH, len(cl)), len(cl), len(hits), time.time() - t0), flush=True)
    with open(os.path.join(HERE, 'names_gen.tsv'), 'w', encoding='utf-8') as o:
        o.write('hash\tpath\n')
        for k, v in sorted(names.items()):
            o.write('%s\t%s\n' % (k, v))
    print('NEW %d names, total %d (%.0fs)' % (len(hits), len(names), time.time() - t0), flush=True)
    c = collections.Counter('/'.join(v.split('/')[:2]) for v in hits.values())
    print('where:', c.most_common(12))
    print('exts:', collections.Counter(os.path.splitext(v)[1].lower() for v in hits.values()).most_common(12))


EXEB = r'D:\TLGL\tlbbgl_x64.exe'

if __name__ == '__main__':
    main()
