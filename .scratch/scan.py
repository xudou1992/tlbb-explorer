import mmap, os, struct, sys

PAKS = ['data.pak', 'data1.pak', 'data2.pak', 'data3.pak', 'data4.pak', 'data_1.pak']
for p in PAKS:
    path = r'D:\TLGL' + '\\' + p
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        hits = []
        pos = 0
        while True:
            i = m.find(b'JPAK', pos)
            if i < 0:
                break
            hits.append(i)
            pos = i + 1
        # zero-run analysis: find end of contiguous non-zero data from the front
        # sample 1MB blocks, classify
        nz_end = 0
        blocks = []
        for off in range(0, size, 1 << 20):
            chunk = m[off:off + (1 << 20)]
            z = chunk.count(0)
            blocks.append(z)
            if z < len(chunk):
                nz_end = off + len(chunk)
        runs = {}
        for i, z in enumerate(blocks):
            kind = 'zero' if z == (1 << 20) else ('part' if z > (1 << 20) // 2 else 'data')
            runs.setdefault(kind, [0, None, None])
            runs[kind][0] += 1
            if runs[kind][1] is None:
                runs[kind][1] = i
            runs[kind][2] = i
        print('%-11s size=%d JPAK@%s lastdataMB=%d' % (p, size, ['0x%x' % h for h in hits[:8]], nz_end >> 20))
        for k, v in runs.items():
            print('     %-6s blocks=%4d  MB-range %d..%d' % (k, v[0], v[1], v[2]))
        m.close()
