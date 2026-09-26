import struct, collections, sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = 'D:/TLGL/.scratch/'
raw = open(BASE + 'out/tree/ResourcePath.cfg', 'rb').read()
hdr = struct.unpack_from('<16I', raw, 0)
N = hdr[9]; REC_OFF = 64; BLOB = 3783792
STRTAB_OFF = REC_OFF + N * 36
NS = (BLOB - STRTAB_OFF) // 8
descs = [struct.unpack_from('<II', raw, STRTAB_OFF + 8*i) for i in range(NS)]
strings = [raw[BLOB+a : BLOB+a+b] for a, b in descs]
ctrl = sum(1 for s in strings if any(c < 9 or (14 <= c < 32) for c in s))
recs = [struct.unpack_from('<9I', raw, REC_OFF + 36*k) for k in range(N)]
pairs = [(strings[f[1]], strings[f[3]]) for f in recs if f[1] < NS and f[3] < NS]
slash_a = sum(1 for x, y in pairs if b'/' in x)
slash_b = sum(1 for x, y in pairs if b'/' in y)
path_is_a = slash_a > slash_b
paths = [ (x if path_is_a else y).decode('latin1') for x, y in pairs ]
keys   = [ (y if path_is_a else x).decode('latin1') for x, y in pairs ]
print(f'N={N} strings={NS} ctrl={ctrl} pairs={len(pairs)} slash_in_a={slash_a} slash_in_b={slash_b}')
print(f'paths={len(paths)} distinct={len(set(paths))}  keys={len(keys)} distinct={len(set(keys))}')
pext = collections.Counter(p.rsplit('.',1)[-1].lower() if '.' in p else '(none)' for p in paths)
kext = collections.Counter(k.rsplit('.',1)[-1].lower() if '.' in k else '(none)' for k in keys)
print('path ext top8:', pext.most_common(8))
print('key  ext top8:', kext.most_common(8))
open(BASE+'cfg_paths.txt','w',encoding='utf-8').write('\n'.join(paths))
open(BASE+'cfg_keys.txt','w',encoding='utf-8').write('\n'.join(keys))

c = sqlite3.connect('file:' + BASE + 'resources.db?mode=ro', uri=True)
cols = [r[1] for r in c.execute('PRAGMA table_info(refs)')]
print('\nrefs columns:', cols)
named = {p.replace(chr(92),'/').lower() for (p,) in c.execute('select path from resources where named=1')}
pset = {p.replace(chr(92),'/').lower() for p in paths}
overlap = len(pset & named)
gap = pset - named
gext = collections.Counter(p.rsplit('.',1)[-1].lower() if '.' in p else '(none)' for p in gap)
print(f'cfg paths vs db named: overlap={overlap} cfg_only={len(gap)} db_only={57274-overlap}')
print('cfg_only ext top8:', gext.most_common(8))
print('cfg_only sample:', sorted(gap)[:8])

name_col = 'name' if 'name' in cols else None
to_col = 'to_hash' if 'to_hash' in cols else None
TEX = ('.tga','.dds','.png','.jpg','.bmp')
dangling = set()
if name_col and to_col:
    for (nm, th) in c.execute(f'select {name_col}, {to_col} from refs'):
        low = (nm or '').lower()
        if low.endswith(TEX) and (th is None or th == 0 or th == ''):
            dangling.add(nm)
    print(f'\ndangling texture names (refs.{name_col}, unresolved via {to_col}): {len(dangling)}')
open(BASE+'mtl_dangling_names.txt','w',encoding='utf-8').write('# count=%d\n' % len(dangling) + '\n'.join(sorted(dangling)))
# joins
dang_low = {d.lower() for d in dangling}
klow = {k.lower() for k in keys}
plow_base = {p.replace(chr(92),'/').rsplit('/',1)[-1].lower() for p in paths}
hit_k = dang_low & klow
hit_b = dang_low & plow_base
print(f'\n[JOIN] dangling ∩ cfg keys: {len(hit_k)}')
print(f'[JOIN] dangling ∩ cfg path basenames: {len(hit_b)}')
print(f'[JOIN] dangling explained by cfg (either): {len(hit_k | hit_b)} / {len(dang_low)} = {100*len(hit_k|hit_b)/max(1,len(dang_low)):.1f}%')
print('  sample key-hits:', sorted(hit_k)[:10])
print('  sample base-hits:', sorted(hit_b)[:10])
# how many cfg_only tga paths
tga_gap = [p for p in gap if p.lower().endswith('.tga')]
print(f'\ncfg_only .tga paths: {len(tga_gap)}   (dangling pool: {len(dang_low)})')
print('  sample:', tga_gap[:8])
