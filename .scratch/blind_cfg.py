import sys, re, struct, collections, sqlite3
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings, u32le

R = Reader()
c = conn()
q = lambda s: [tuple(r) for r in c.execute(s).fetchall()]

print('=== locate ResourcePath.cfg ===')
rows = q("select hash,path,dir,name,ext,type,subtype,stored,original,src,props from resources where lower(name) like '%resourcepath%' or lower(path) like '%resourcepath%'")
for r in rows:
    print('  ', r)
other = q("select hash,path,ext,type,subtype,stored,original from resources where ext in ('.cfg','.ini','.tab','.json','.dat','.txt') ")
print('  config-ish files:', other[:20])

print('\n=== decode it ===')
row = c.execute("select * from resources where lower(name) like '%resourcepath%' limit 1").fetchone()
if row is None:
    print('  NOT FOUND in db')
else:
    b, why = R.get(row)
    print('  ', row['path'], why, len(b) if b else None, 'stored', row['stored'], 'original', row['original'])
    if b:
        print('   hex[0:96]', b[:96].hex(' '))
        print('   head ascii', repr(b[:96]))
        print('   u32x8', u32le(b, 8))
        ss = strings(b, 400000)
        print('   printable tokens:', len(ss), 'sample', ss[:12])
        tail = b[-96:]
        print('   tail hex', tail.hex(' '))
        print('   tail ascii', repr(tail))
        # count path-like tokens
        pats = [s for s in ss if '/' in s or '\\' in s]
        print('   path-like tokens:', len(pats), pats[:6], pats[-4:])
        ext = collections.Counter(s[s.rfind('.'):].lower() for s in pats if '.' in s[-12:])
        print('   ext hist of cfg entries:', ext.most_common(20))
