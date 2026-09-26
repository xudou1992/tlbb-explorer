import struct, collections, sqlite3, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = 'D:/TLGL/.scratch/'
raw = open(BASE + 'out/tree/ResourcePath.cfg', 'rb').read()
STRTAB = 2619552
size, flag, count = struct.unpack_from('<II', raw[STRTAB+8:STRTAB+16], 0)[0:3] if False else (None,None,None)
_id, size, flag, count = struct.unpack_from('<4I', raw, STRTAB)
print(f'strtab id={_id} size={size} flag={flag} count={count}')
DESC = STRTAB + 16
CHARS = DESC + 8 * count
print(f'desc@{DESC} chars@{CHARS} chars_len={len(raw)-CHARS} declared_area={size-8-8*count}')
lens = struct.unpack_from('<%dI' % count, raw, DESC)
hashes = struct.unpack_from('<%dI' % count, raw, DESC + 4*count)
total = sum(lens)
print(f'sum(len)={total} vs chars_len={len(raw)-CHARS}  slack={len(raw)-CHARS-total}')
strings = []
p = CHARS
bad = 0
for L in lens:
    s = raw[p:p+L]; p += L
    try:
        t = s.decode('utf-8')
    except UnicodeDecodeError:
        t = s.decode('latin1'); bad += 1
    strings.append(t)
print(f'strings decoded: {len(strings)}, non-utf8(latin1 fallback): {bad}')
slash = sum(1 for s in strings if '/' in s)
print(f'contain "/": {slash} / {len(strings)}')
ext = collections.Counter(s.rsplit('.',1)[-1].lower() if '.' in s.rsplit('/',1)[-1] else '(none)' for s in strings)
print('ext top12:', ext.most_common(12))
print('first 6 strings:', strings[:6])
# pairwise hypothesis: (2j, 2j+1) = (name, path)?
pw = [(strings[2*j], strings[2*j+1]) for j in range(count//2)]
both_slash = sum(1 for a,b in pw if '/' in a and '/' in b)
no_slash_a = sum(1 for a,b in pw if '/' not in a)
print(f'pairwise {len(pw)}: a-no-slash={no_slash_a} both-slash={both_slash}')
print('pair samples:', pw[:4])

c = sqlite3.connect('file:' + BASE + 'resources.db?mode=ro', uri=True)
named = {q.replace(chr(92),'/').lower() for (q,) in c.execute('select path from resources where named=1')}
sset = {s.replace(chr(92),'/').lower() for s in strings}
inter = sset & named
print(f'\n[cfg vs db] strings ∩ db named: {len(inter)}')
only = sset - named
oext = collections.Counter(s.rsplit('.',1)[-1].lower() if '.' in s.rsplit('/',1)[-1] else '(none)' for s in only)
print(f'cfg strings NOT in db: {len(only)}  ext top8: {oext.most_common(8)}')
print('cfg-only sample:', sorted(only)[:10])

# refs schema + dangling texture names
cols = [r[1] for r in c.execute('PRAGMA table_info(refs)')]
print('\nrefs cols:', cols)
name_col = 'name' if 'name' in cols else ('ref' if 'ref' in cols else None)
TEX = ('.tga','.dds','.png','.jpg','.bmp','.webp')
dangling = set()
resolved = 0
if name_col:
    tocols = [x for x in cols if x in ('to_hash','target','to')]
    to_col = tocols[0] if tocols else None
    kindc = 'kind' if 'kind' in cols else None
    sel = f'select {name_col}' + (f', {to_col}' if to_col else '')
    for row in c.execute(sel + ' from refs'):
        nm = row[0] or ''
        th = row[1] if to_col and len(row)>1 else None
        if nm.lower().endswith(TEX):
            if th is None or th == 0 or th == '':
                dangling.add(nm)
            else:
                resolved += 1
    print(f'texture-name refs: resolved={resolved} dangling_distinct={len(dangling)}')
    open(BASE+'mtl_dangling_names.txt','w',encoding='utf-8').write('# count=%d\n' % len(dangling) + '\n'.join(sorted(dangling)))
    dlow = {d.lower() for d in dangling}
    hit = dlow & sset
    print(f'\n[JOIN] dangling ∩ cfg strings: {len(hit)} / {len(dlow)} = {100*len(hit)/max(1,len(dlow)):.1f}%')
    print('  sample hits:', sorted(hit)[:12])
    miss = dlow - sset
    print(f'  still unexplained: {len(miss)}; sample:', sorted(miss)[:8])
