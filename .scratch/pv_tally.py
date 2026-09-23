"""One-off: final tally -- record-level previewability classes + named coverage."""
import os, sys, sqlite3, struct, collections, re
HERE = os.path.dirname(os.path.abspath(__file__))
ALL = os.path.join(HERE, 'out', 'all')
FIND = {}
for pak in sorted(os.listdir(ALL)):
    d = os.path.join(ALL, pak)
    if not os.path.isdir(d):
        continue
    for fn in os.listdir(d):
        if len(fn) >= 16:
            FIND.setdefault(fn[:16], os.path.join(d, fn))
con = sqlite3.connect(os.path.join(HERE, 'resources.db'))
rec_of = dict(con.execute("select hash,count(*) from records group by 1"))
TOTAL = sum(rec_of.values())
ASCII = re.compile(rb'^[\t\r\n\x20-\x7e]+$')


def classify(h, typ):
    """-> (class, label). 0 zero-cost, 1 thin converter, 2 deep RE, 3 no data."""
    p = FIND.get(h)
    if not p:
        return 3, 'no-payload'
    b = open(p, 'rb').read(8192)
    if not b:
        return 3, 'empty'
    m4 = b[:4]
    if m4 == b'JMT1':
        tag = b[4:8].decode('latin1')
        sub, blob, w, h2, mips, l0 = struct.unpack_from('<IIHHII', b, 8)
        if tag == 'COLW':
            return 0, 'JMT1/COLW=webp'
        if tag == 'DXT1':
            return 1, 'JMT1/DXT1->%s' % ('BC1' if sub == 0x83f0 else 'BC3')
        if tag in ('RGBA', 'COLR', 'ALI8'):
            return 1, 'JMT1/%s->raw' % tag
        return 1, 'JMT1/%s' % tag
    if m4 == b'RIFF':
        return (0, 'riff/WEBP') if b[8:12] == b'WEBP' else (0, 'riff/WAVE')
    if b[:4] in (b'OggS', b'\x89PNG') or b[:3] == b'\xff\xd8\xff':
        return 0, ('ogg' if b[:4] == b'OggS' else 'png' if b[:4] == b'\x89PNG' else 'jpeg')
    if b[:3] == b'ID3' or (b[0] == 0xFF and b[1] & 0xE0 == 0xE0):
        return 0, 'mp3'
    bad = sum(1 for x in b if x < 32 and x not in (9, 10, 13) or x == 127)
    if bad <= 0.02 * len(b):
        if ASCII.match(b):
            return 0, 'text/ascii'
        for enc in ('utf-8', 'gbk'):
            try:
                b.decode(enc)
                return 0, 'text/' + enc
            except Exception:
                pass
        return 0, 'text/8bit'
    if m4 in (b'JBCF',):
        return 1, 'JBCF property-list'
    if m4 in (b'JLUA', b'JSTR'):
        return 0, m4.decode()
    if m4 == b'GATA':
        return 2, 'GATA timeline'
    if m4 == b'JBPU':
        return 2, 'JBPU particle'
    if m4 == b'NAVF':
        return 2, 'NAVF navmesh'
    if b[:10] == b'Copyright ':
        return 2, 'banner/' + b[64:72].split(b'\0')[0].decode('latin1').strip()
    a = struct.unpack_from('<2I', b.ljust(8, b'\0'), 0)
    if a[1] == 753:
        return 2, 'scene grid753'
    if a[1] == 280:
        return 2, 'mapref tab280'
    if len(b) <= 8:
        return 3, 'tiny'
    return 2, 'binary/' + m4.hex()


rows = collections.defaultdict(lambda: [0, 0, 0])
per = collections.defaultdict(collections.Counter)
per_h = collections.defaultdict(collections.Counter)
named_rec = named_h = 0
named_ab = 0
cache = {}
for h, typ, orig, named in con.execute("select hash,type,original,named from resources"):
    c, lab = cache[h] = classify(h, typ)
    r = rec_of.get(h, 0)
    rows[c][0] += r
    rows[c][1] += 1
    rows[c][2] += orig or 0
    per[typ][(c, lab)] += r
    per_h[typ][(c, lab)] += 1
    if named:
        named_rec += r
        named_h += 1
        if c <= 1:
            named_ab += r
    if typ == 'texture' and named:
        pass

lab = {0: 'A zero-cost', 1: 'B converter', 2: 'C deep-RE', 3: 'D no-data'}
print('records=%d  hashes=%d  named hashes=%d  named records=%d' %
      (TOTAL, len(cache), named_h, named_rec))
for c in sorted(rows):
    r, hh, by = rows[c]
    print('  %-14s records %7d (%5.2f%%) | hashes %6d (%5.2f%%) | %6.2f GB (%4.1f%%)' %
          (lab[c], r, 100.0 * r / TOTAL, hh, 100.0 * hh / len(cache), by / 1e9,
           100.0 * by / (sum(x[2] for x in rows.values()) or 1)))
print('  A+B = %d records = %.2f%% of all records' %
      (rows[0][0] + rows[1][0], 100.0 * (rows[0][0] + rows[1][0]) / TOTAL))
print('  A+B that carry a real path name: %d records = %.2f%% of all records, %.1f%% of A+B'
      % (named_ab, 100.0 * named_ab / TOTAL, 100.0 * named_ab / (rows[0][0] + rows[1][0])))

print('\n---- record counts by type / class ----')
for typ in sorted(per, key=lambda t: -sum(per[t].values())):
    tot = sum(per[typ].values())
    print('  %-9s %7d | %s' % (typ, tot, ', '.join('%s:%s=%d' % (lab[c][0], w, n)
                                                    for (c, w), n in per[typ].most_common(4))))

print('\n---- texture named coverage ----')
hh, nm = con.execute("select count(*),sum(named) from resources where type='texture'").fetchone()
print('  hashes %d named %d (%.1f%%) unnamed %d' % (hh, nm, 100.0 * nm / hh, hh - nm))
tn = sum(rec_of[h] for h, in con.execute("select hash from resources where type='texture'"))
tnn = sum(rec_of[h] for h, n in con.execute(
    "select hash,named from resources where type='texture'") if n)
print('  records %d named %d (%.1f%%)' % (tn, tnn, 100.0 * tnn / tn))
for e, in con.execute("select distinct ext from resources where type='texture' and named=1"):
    print('   named texture extension:', e, con.execute(
        "select count(*) from resources where type='texture' and named=1 and ext=?",
        (e,)).fetchone()[0])
