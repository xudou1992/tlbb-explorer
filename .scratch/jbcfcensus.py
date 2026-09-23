"""Census the JBCF family: header fields, body shape, string table, record stride.

13,403 resources are tagged JBCF with a single subtype, so the container is being
recognised but not read. This dumps what the bodies actually look like so a real
grammar can be pinned down.
"""
import collections
import json
import os
import sqlite3
import struct
import sys

HERE = r'D:\TLGL\.scratch'
OUT = os.path.join(HERE, 'jbcf_census.txt')


def payload_index():
    idx = {}
    for pak in os.listdir(os.path.join(HERE, 'out', 'all')):
        d = os.path.join(HERE, 'out', 'all', pak)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if len(fn) >= 16:
                idx[fn[:16]] = os.path.join(d, fn)
    return idx


def main():
    con = sqlite3.connect('file:%s?mode=ro' % os.path.join(HERE, 'resources.db'), uri=True)
    rows = con.execute(
        "select hash, pak, original, occupied, ver, method, path, props from resources"
        " where type in ('JBCF','JBPU','NAVF','JLUA','JMDL','JSTR','JPKF')").fetchall()
    idx = payload_index()
    log = open(OUT, 'w', encoding='utf-8')

    def p(*a):
        print(*a, file=log)

    stat = collections.Counter()
    f4 = collections.Counter()
    f8 = collections.Counter()
    f12rel = collections.Counter()
    s16 = collections.Counter()
    samples = collections.defaultdict(list)
    strings_at = collections.Counter()
    sizes = collections.defaultdict(list)

    for h, pak, orig, occ, ver, meth, path, props in rows:
        f = idx.get(h)
        if not f or not os.path.isfile(f):
            stat['no payload'] += 1
            continue
        with open(f, 'rb') as fh:
            head = fh.read(1024)
        if len(head) < 16:
            stat['short'] += 1
            continue
        a = struct.unpack_from('<4I', head, 0)
        tag = head[:4].decode('latin1', 'replace')
        stat[tag] += 1
        sizes[tag].append(orig or len(head))
        f4[(tag, a[1])] += 1
        f8[(tag, a[2])] += 1
        f12rel[(tag, (orig or 0) - a[3])] += 1
        s16[(tag, head[16:20].hex())] += 1
        if len(samples[tag]) < 6:
            samples[tag].append((h, orig, path, head[:160].hex(), a))

    p('=== rows: %d  missing payload: %d ===' % (len(rows), stat['no payload']))
    for tag, n in stat.most_common():
        if tag == 'no payload':
            continue
        sz = sorted(sizes[tag])
        p('\n## %s  n=%d  size min/med/max = %d/%d/%d  total=%d' %
          (tag, n, sz[0], sz[len(sz) // 2], sz[-1], sum(sz)))
        p('   f4 top: %s' % f4.most_common(6))
        p('   f8 top: %s' % [x for x in f8.most_common(6) if x[0][0] == tag])
        p('   orig-f12 top: %s' % [x for x in f12rel.most_common(6) if x[0][0] == tag])
        p('   bytes16-20 top: %s' % [x for x in s16.most_common(8) if x[0][0] == tag])
        for h, orig, path, hx, a in samples[tag][:4]:
            p('   - %s orig=%s hdr=%s path=%s' % (h, orig, a, path))
            p('     %s' % hx)
    log.close()
    print(open(OUT, encoding='utf-8').read()[:4000])


if __name__ == '__main__':
    main()
