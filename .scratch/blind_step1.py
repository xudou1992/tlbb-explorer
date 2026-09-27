import sys, sqlite3, struct, re, random, collections
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_read import read, c

def head_u32(b, n=6):
    return list(struct.unpack('<%dI' % min(n, len(b)//4), b[:4*min(n, len(b)//4)]))

def strs(b, minlen=4, limit=20):
    return [s.decode('latin1') for s in re.findall(rb'[\x20-\x7e]{%d,}' % minlen, b)[:limit]]

print('=== NAMED .mesh samples (type=mesh subtype=copy) ===')
rows = c.execute("select hash,path,original,src from resources where ext='.mesh' and named=1 limit 6").fetchall()
for h, p, o, src in rows:
    b, why, _ = read(h)
    print(p, '|', why, len(b) if b else None, 'declared_orig', o, 'src', src)
    if b:
        print('   hex ', b[:32].hex(' '))
        print('   text', repr(b[:64]))
        print('   u32', head_u32(b, 8))

print()
print('=== mesh type/subtype/ext combos ===')
for r in c.execute("select type,subtype,ext,count(*),sum(original) from resources where ext in ('.mesh','.mdl') or type='mesh' group by 1,2,3 order by 4 desc limit 20"):
    print('  ', r)

print()
print('=== GEOM raw samples ===')
rows = c.execute("select hash,original,props,flags,method from resources where type='geom' limit 12").fetchall()
for h, o, props, fl, me in rows[:12]:
    b, why, _ = read(h)
    print(h, why, len(b) if b else None, 'orig', o, props)
    if b:
        print('   hex ', b[:48].hex(' '))
        print('   u32 ', head_u32(b, 8))
        print('   strs', strs(b[:4096], 5, 8))
        print('   tail', b[-24:].hex(' '))
