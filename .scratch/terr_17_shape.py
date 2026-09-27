import struct, collections, sys, re, os

name = 'w1351_ll_dl_002'
base = 'out/tree/mobile_maps/' + name
d = open(base + '/' + name + '.map', 'rb').read()
magic, A, B, hdr = struct.unpack('<4I', d[:16]); nb = A*B
end = struct.unpack('<I', d[16:20])[0]; blk = (end-hdr)//nb
v = d[hdr:end]
W, H = A*32, B*32
g = [0]*(W*H)
for gy in range(B):
    for gx in range(A):
        o = (gy*A+gx)*blk
        for k in range(1024):
            r, c = divmod(k, 32)
            g[(gy*32+r)*W + gx*32+c] = (v[o+k*4+1] << 8) | v[o+k*4+2]
gc = collections.Counter(g)
top = [k for k, _ in gc.most_common(11)]
idx = {k: i for i, k in enumerate(top)}
co = [[0]*len(top) for _ in top]
for y in range(H):
    row = y*W
    for x in range(W-1):
        a, b = g[row+x], g[row+x+1]
        if a in idx and b in idx: co[idx[a]][idx[b]] += 1
for y in range(H-1):
    for x in range(W):
        a, b = g[y*W+x], g[(y+1)*W+x]
        if a in idx and b in idx: co[idx[a]][idx[b]] += 1
print('code = (b1<<8)|b2 ; co-occurrence of 4-neighbours (rows=value, cols=neighbour)')
hdr_line = 'val   n%    ' + ''.join('%9s' % ('%d,%d' % (k >> 8, k & 255)) for k in top)
print(hdr_line)
tot = sum(gc.values())
for i, k in enumerate(top):
    s = sum(co[i])
    print('(%2d,%2d) %6.2f%%' % (k >> 8, k & 255, 100.0*gc[k]/tot) + ''.join('%9.3f' % (co[i][j]/s) for j in range(len(top))))
print()
# shape of each class: mean cluster "thickness": fraction of class cells with >=3 same-class neighbours
for k in top:
    cells = [(x, y) for y in range(H) for x in range(W) if g[y*W+x] == k]
    if len(cells) < 50: continue
    s = set(cells)
    deg = collections.Counter()
    per = 0
    for (x, y) in cells:
        n = sum(1 for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)) if (x+dx, y+dy) in s)
        deg[n] += 1; per += n
    # components
    seen = set(); comps = []
    for c0 in cells:
        if c0 in seen: continue
        stack = [c0]; seen.add(c0); m = 0
        while stack:
            x, y = stack.pop(); m += 1
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                q = (x+dx, y+dy)
                if q in s and q not in seen: seen.add(q); stack.append(q)
        comps.append(m)
    comps.sort(reverse=True)
    print('(b1,b2)=(%2d,%2d) n=%-7d mean same-class deg %.2f  deg0(isolated)=%.1f%%  components=%d  largest=%d  %s' %
          (k >> 8, k & 255, len(cells), per/len(cells), 100.0*deg[0]/len(cells), len(comps), comps[0], comps[:6]))
# sfl
s = open(base + '/' + name + '.sfl', 'rb').read()
st = [x.decode('latin1') for x in re.findall(rb'[ -~]{5,}', s)]
print('\n.sfl size', len(s), 'strings', len(st), 'distinct', len(set(st)))
print(' sfl sample', st[:12])
print(' ext counts', collections.Counter(os.path.splitext(x)[1] for x in st).most_common(6))
print(' does sfl mention map name / tani?', any(name in x for x in st), any('tani' in x for x in st))
