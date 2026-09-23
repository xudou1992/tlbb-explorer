"""One-off: for every resource, decide 'how previewable is it today' --
magic + text-encoding census keyed by content and by the real extension."""
import os, sqlite3, struct, collections, re

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
rows = list(con.execute("select hash,path,type,codec,ext,original,named from resources"))
ASCII = re.compile(rb'^[\t\r\n\x20-\x7e]+$')


def ctrl_ratio(b):
    bad = sum(1 for x in b if x < 32 and x not in (9, 10, 13) or x == 127)
    return bad / max(1, len(b))


def sniff(b):
    if not b:
        return 'empty'
    m4 = b[:4]
    if m4 == b'JMT1':
        return 'JMT1/' + b[4:8].decode('latin1')
    if b[:10] == b'Copyright ':
        return 'banner/' + b[64:72].split(b'\0')[0].decode('latin1').strip()
    if m4 in (b'JBCF', b'JBPU', b'NAVF', b'GATA', b'JLUA', b'JMDL', b'JSTR'):
        return m4.decode('latin1')
    if b[:4] == b'RIFF':
        return 'riff/' + b[8:12].decode('latin1')
    if b[:4] == b'OggS':
        return 'ogg'
    if b[:3] == b'ID3' or (b[0] == 0xFF and b[1] & 0xE0 == 0xE0):
        return 'mp3'
    if b[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if b[:3] == b'\xff\xd8\xff':
        return 'jpeg'
    if ctrl_ratio(b) < 0.02:
        if ASCII.match(b):
            return 'text/ascii'
        try:
            b.decode('utf-8')
            return 'text/utf8'
        except Exception:
            pass
        try:
            b.decode('gbk')
            return 'text/gbk'
        except Exception:
            return 'text/mixed-8bit'
    return 'bin/' + m4.hex()


tab = collections.defaultdict(collections.Counter)
ext_tab = collections.defaultdict(collections.Counter)
bytes_by = collections.Counter()
sn = {}
rec_of = dict(con.execute("select hash,count(*) from records group by 1"))
rec_by_sn = collections.Counter()
rec_by_type_sn = collections.defaultdict(collections.Counter)
for h, path, typ, codec, ext, orig, named in rows:
    p = FIND.get(h)
    s = 'no-payload' if not p else sn.setdefault(h, sniff(open(p, 'rb').read(8192)))
    tab[typ][s] += 1
    ext_tab[ext or '(unnamed)'][s] += 1
    bytes_by[(typ, s)] += orig or 0
    rec_by_sn[s] += rec_of.get(h, 0)
    rec_by_type_sn[typ][s] += rec_of.get(h, 0)

print('======== content magic by declared type (unique hashes) ========')
for t in sorted(tab, key=lambda x: -sum(tab[x].values())):
    print('%-9s %6d | %s' % (t, sum(tab[t].values()),
                             ', '.join('%s=%d' % (k, v) for k, v in tab[t].most_common(5))))

print('\n======== content magic by real extension ========')
for e in sorted(ext_tab, key=lambda x: -sum(ext_tab[x].values()))[:24]:
    print('%-9s %6d | %s' % (e, sum(ext_tab[e].values()),
                             ', '.join('%s=%d' % (k, v) for k, v in ext_tab[e].most_common(4))))

print('\n======== RECORD counts by content magic (total %d) ========' % sum(rec_by_sn.values()))
for k, v in rec_by_sn.most_common(40):
    print('   %-24s %8d  %5.2f%%' % (k, v, 100.0 * v / sum(rec_by_sn.values())))

print('\n======== bytes by (type, magic) ========')
tot = sum(bytes_by.values())
for (t, s), b in bytes_by.most_common(16):
    print('   %-10s %-20s %7.1f MB' % (t, s, b / 1e6))
print('   total %.2f GB' % (tot / 1e9))
