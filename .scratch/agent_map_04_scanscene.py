import numpy as np, re, os, io, struct, collections, glob
o = io.open('agent_map_04_scanscene.txt','w',encoding='utf-8')
def W(*a): o.write(' '.join(str(x) for x in a)+'\n')

STR = re.compile(rb'[\x20-\x7e]{4,}')

def scan(path):
    raw = open(path,'rb').read()
    W('\n#### %s  size=%d' % (path, len(raw)))
    W('u32[0:8]:', struct.unpack_from('<8I', raw, 0))
    W('f32[0:24] @0x08:', [round(f,4) for f in struct.unpack_from('<24f', raw, 8)])
    strs = [(m.start(), m.group().decode('latin1')) for m in STR.finditer(raw)]
    W('n_strings>=4:', len(strs))
    ext = collections.Counter()
    for p,s in strs:
        mm = re.search(r'\.([A-Za-z]{2,5})$', s)
        ext[mm.group(1) if mm else '(noext)'] += 1
    W('string ext histogram:', dict(ext.most_common(12)))
    meshish = [(p,s) for p,s in strs if re.search(r'\.(mesh|tga|dds|mtl|scene)$', s)]
    W('n asset-like strings:', len(meshish), 'first 12:', meshish[:12])
    # pointer density
    u64 = np.frombuffer(raw[:len(raw)//8*8], dtype='<u8')
    ptr = ((u64 >> 32) >= 0x7f00) & ((u64 >> 32) <= 0x7fff) & ((u64 & 0xffffffff) != 0)
    idx = np.nonzero(ptr)[0] * 8
    W('n 0x7f.. u64 (aligned):', len(idx), 'density per KB: %.2f' % (len(idx)*1024.0/len(raw)))
    if len(idx): W('  ptr span: %d .. %d, first 10:' % (idx[0], idx[-1]), list(idx[:10]))
    # pointer density in 4KB windows
    nb = len(raw)//4096+1
    hist = np.zeros(nb, dtype=int)
    for i in idx: hist[i//4096]+=1
    W('  per-4KB ptr counts:', ' '.join(str(int(x)) for x in hist))
    return raw, strs, idx

for f in sorted(glob.glob('out/tree/mobile_maps/w1351_ll_dl_002/*.scene'))[:4]:
    scan(f)
scan('out/tree/mobile_maps/w1351_fb_jiehun_001/1_3_-5.scene')
o.close(); print('ok')
