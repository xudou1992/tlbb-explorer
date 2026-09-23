"""Bootstrap naming: mine path tokens out of every extracted asset, hash-match to index."""
import os
import re
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from jhash import path_hash

M32 = 0xFFFFFFFF
HERE = r'D:\TLGL\.scratch'
ROOT = os.path.join(HERE, 'out', 'all')
maxb = int(sys.argv[1]) if len(sys.argv) > 1 else 200 * 1024 * 1024

EXTS = ('png', 'tga', 'dds', 'jpg', 'jpeg', 'bmp', 'gif', 'ico', 'wav', 'ogg', 'mp3', 'mp4', 'usm',
        'lua', 'xml', 'tab', 'mesh', 'jmt', 'jstr', 'jlua', 'cfg', 'ini', 'txt', 'json', 'bytes',
        'skel', 'atlas', 'swf', 'ttf', 'glsl', 'hlsl', 'fx', 'pak', 'pcfg', 'gameclient',
        'ani', 'act', 'eff', 'mdl', 'tex', 'webm', 'webp', 'font', 'bin', 'res', 'dat')
tokre = re.compile(br'[^\x00-\x20\x7f-\xff/\\]{0,150}(?:/|\\)[^\x00-\x20\x7f-\xff]{0,150}'
                   br'\.(?:' + b'|'.join(e.encode() for e in EXTS) + br')(?![A-Za-z0-9])', re.I)

targets = set()
with open(os.path.join(HERE, 'index.tsv'), encoding='utf-8') as f:
    next(f)
    for line in f:
        targets.add(int(line.split('\t', 1)[0], 16))

done = {}
if os.path.isfile(os.path.join(HERE, 'names.tsv')):
    with open(os.path.join(HERE, 'names.tsv'), encoding='utf-8') as f:
        next(f)
        for line in f:
            a = line.rstrip('\n').split('\t')
            done[a[0]] = a[1]


def hbytes(b):
    h1, h2 = 0x4E67C6A7, 0
    for c in b:
        if 65 <= c <= 90:
            c += 32
        elif c == 92:
            c = 47
        h1 ^= (c + 32 * h1 + (h1 >> 2)) & M32
        h1 &= M32
        h2 = (c + 65599 * h2) & M32
    return h1 | (h2 << 32)


hits = {}
nfiles = 0
nbytes = 0


def try_token(t):
    if len(t) < 5:
        return
    for cand in (t, t.lstrip(b'./ ')):
        for enc in (cand, cand.decode('gbk', 'ignore').encode('utf-8')):
            h = hbytes(enc)
            if h in targets:
                k = '%016x' % h
                if k not in hits and k not in done:
                    hits[k] = cand.decode('gbk', 'replace')
                return


for stem in sorted(os.listdir(ROOT)):
    base = os.path.join(ROOT, stem)
    if not os.path.isdir(base):
        continue
    for root, _d, fs in os.walk(base):
        for fn in fs:
            p = os.path.join(root, fn)
            try:
                sz = os.path.getsize(p)
                if sz > maxb:
                    continue
                b = open(p, 'rb').read()
            except OSError:
                continue
            nfiles += 1
            nbytes += sz
            for m in tokre.finditer(b):
                try_token(m.group())
            if nfiles % 5000 == 0:
                print('... %d files, %d hits' % (nfiles, len(hits)), flush=True)

with open(os.path.join(HERE, 'names_new.tsv'), 'w', encoding='utf-8') as o:
    o.write('hash\tpath\n')
    for k, v in sorted(hits.items()):
        o.write('%s\t%s\n' % (k, v))
print('scanned %d files / %.2f GB -> %d new names (seed %d, targets %d)' % (
    nfiles, nbytes / 1e9, len(hits), len(done), len(targets)))
