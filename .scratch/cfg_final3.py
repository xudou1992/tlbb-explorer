import struct, collections, sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = 'D:/TLGL/.scratch/'
raw = open(BASE + 'out/tree/ResourcePath.cfg', 'rb').read()
STRTAB = 2619552
_id, size, flag, count = struct.unpack_from('<4I', raw, STRTAB)
DESC = STRTAB + 16
CHARS = DESC + 8 * count
arr = struct.unpack_from('<%dI' % (2*count), raw, DESC)
lens, hashes = arr[0::2], arr[1::2]
total = sum(lens)
print(f'count={count} sum(len)={total} chars_len={len(raw)-CHARS} slack={len(raw)-CHARS-total}')
strings = []
p = CHARS
for L in lens:
    strings.append(raw[p:p+L].decode('utf-8')); p += L
print(f'decoded {len(strings)}; last ends at {p} == file size {len(raw)}: {p==len(raw)}')
slash = sum(1 for s in strings if '/' in s)
print(f'paths(with /): {slash}  bare names: {len(strings)-slash}')
ext = collections.Counter(s.rsplit('.',1)[-1].lower() for s in strings if '.' in s.rsplit('/',1)[-1])
print('ext top12:', ext.most_common(12))
pairs = [(strings[2*j], strings[2*j+1]) for j in range(count//2)]
ok = sum(1 for a,b in pairs if '/' in b and ('/' not in a) and b.endswith(a))
print(f'pairwise (bare, path) pattern holds: {ok}/{len(pairs)}')
print('pair samples:', pairs[1000:1003], pairs[50000:50001])
open(BASE+'cfg_paths.txt','w',encoding='utf-8').write('\n'.join(b for a,b in pairs))
open(BASE+'cfg_keys.txt','w',encoding='utf-8').write('\n'.join(a for a,b in pairs))

c = sqlite3.connect('file:' + BASE + 'resources.db?mode=ro', uri=True)
named = {q.replace(chr(92),'/').lower() for (q,) in c.execute('select path from resources where named=1')}
psub = {b.replace(chr(92),'/').lower() for a,b in pairs}
inter = psub & named
only = psub - named
print(f'\n[cfg vs db] path overlap={len(inter)}  cfg_only={len(only)}  db_named_total={len(named)}')
oext = collections.Counter(s.rsplit('.',1)[-1].lower() for s in only if '.' in s.rsplit('/',1)[-1])
print('cfg_only ext top10:', oext.most_common(10))
tga_only = sorted(s for s in only if s.endswith('.tga'))
print('cfg_only .tga:', len(tga_only), 'sample:', tga_only[:6])

cols = [r[1] for r in c.execute('PRAGMA table_info(refs)')]
name_col = 'name' if 'name' in cols else None
to_col = 'to_hash' if 'to_hash' in cols else None
TEX = ('.tga','.dds','.png','.jpg','.bmp','.webp')
dangling = set()
if name_col and to_col:
    for nm, th in c.execute(f'select {name_col}, {to_col} from refs'):
        if (nm or '').lower().endswith(TEX) and (th is None or th == 0 or th == ''):
            dangling.add(nm)
print(f'\nrefs cols={cols}\ndangling texture names: {len(dangling)}')
open(BASE+'mtl_dangling_names.txt','w',encoding='utf-8').write('# count=%d\n' % len(dangling) + '\n'.join(sorted(dangling)))
dlow = {d.lower() for d in dangling}
klow = {a.lower() for a,b in pairs}
plbase = {b.replace(chr(92),'/').rsplit('/',1)[-1].lower() for a,b in pairs}
hk = dlow & klow; hb = dlow & plbase
print(f'[JOIN] dangling ∩ cfg bare keys: {len(hk)}')
print(f'[JOIN] dangling ∩ cfg path basenames: {len(hb)}')
print(f'[JOIN] dangling explained by cfg: {len(hk|hb)} / {len(dlow)} = {100*len(hk|hb)/max(1,len(dlow)):.1f}%')
print('  key-hit sample:', sorted(hk)[:8])
print('  base-hit sample:', sorted(hb)[:8])
