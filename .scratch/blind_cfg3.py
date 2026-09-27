"""Are the recovered grid-scene paths present in the official ResourcePath.cfg string pool?"""
import re
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader  # noqa: E402
from jhash import path_hash  # noqa: E402

C = conn()
R = Reader()
cfg = C.execute("select * from resources where hash='4b761249ad5d605c'").fetchone()
cb, _ = R.get(cfg)
print('cfg len', len(cb))

un = {}
for row in C.execute("select * from resources where subtype='grid753' and named=0"):
    un[row['hash']] = row
dirs = [d for (d,) in C.execute("select distinct dir from resources where dir like 'mobile_maps/%'").fetchall()]
found = {}
for d in dirs:
    for a in range(0, 4):
        for y in range(-6, 18):
            for z in range(-18, 6):
                k = '%016x' % path_hash('%s/%d_%d_%d.scene' % (d, a, y, z))
                if k in un:
                    found[k] = '%s/%d_%d_%d.scene' % (d, a, y, z)

print('=== cfg context around recovered leaf names ===')
shown = 0
for h, p in list(found.items()):
    leaf = p.split('/')[-1].encode()
    for m in re.finditer(re.escape(leaf), cb):
        i = m.start()
        ctx = cb[max(0, i - 90):i + len(leaf) + 4]
        if b'mobile_maps' in ctx:
            print('  path=%s' % p)
            print('     cfg ctx=%r' % ctx)
            print('     exact joined string in cfg:', p.encode() in cb)
            shown += 1
            break
    if shown >= 4:
        break

print('\n=== how many ".scene" leaf strings does the cfg hold, and do any match recovered leaves? ===')
scene_tokens = set(re.findall(rb'[0-9a-zA-Z_\-\.]+\.scene', cb))
print('  distinct *.scene tokens in cfg:', len(scene_tokens))
rec_leaves = {p.split('/')[-1].encode() for p in found.values()}
named_leaves = {r[0] for r in C.execute("select name from resources where subtype='grid753' and named=1")}
print('  recovered leaves present as cfg tokens: %d / %d' % (len(rec_leaves & scene_tokens), len(rec_leaves)))
print('  named leaves present as cfg tokens: %d / %d' % (len(named_leaves & scene_tokens), len(named_leaves)))
print('  cfg tokens NOT matching any db .scene name:', len(scene_tokens - named_leaves - rec_leaves))
samp = sorted(scene_tokens - named_leaves - rec_leaves)[:8]
print('  sample of such cfg-only tokens:', [s.decode('latin1') for s in samp])
# do those cfg-only tokens hash to nameless resources?
tok_hits = {}
for d in dirs:
    for t in scene_tokens:
        k = '%016x' % path_hash('%s/%s' % (d, t.decode('latin1')))
        if k in un:
            tok_hits[k] = '%s/%s' % (d, t.decode('latin1'))
print('  cfg-only tokens x map dirs -> additional nameless grid753 recovered: %d (sample %s)'
      % (len(tok_hits), list(tok_hits.values())[:3]))
