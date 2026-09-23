"""Probe the JMT1 DXT1 payload layout: colour chain vs a second alpha chain."""
import struct

import explorer
from PIL import Image

raw = explorer.read_payload('003cdc4f5a52d054')
w, h = struct.unpack_from('<HH', raw, 16)
nmip = struct.unpack_from('<I', raw, 20)[0]
declared = struct.unpack_from('<I', raw, 12)[0]
body = raw[24:]


def mip_sizes(w, h, nmip, block):
    sizes = []
    for i in range(nmip):
        bw = max(1, (w >> i) + 3) // 4
        bh = max(1, (h >> i) + 3) // 4
        sizes.append(bw * bh * block)
    return sizes


sizes = mip_sizes(w, h, nmip, 8)
chain = sum(sizes)
print('declared=%d  one %d-mip DXT1 chain=%d  two chains=%d  tail=%d'
      % (declared, nmip, chain, 2 * chain, declared - 2 * chain))

img0, _ = explorer.decode_jmt1(raw[:24 + sizes[0]])
img0.save('probe_mip0.png')
print('mip0 alone:', img0.size)

# second half as an alpha-ish DXT1 chain -> grayscale preview
off = 24 + chain
second = b'JMT1' + b'DXT1' + raw[8:24] + body[chain:]
img1, info1 = explorer.decode_jmt1(second)
g = img1.convert('RGB').point(lambda v: v)
g.save('probe_second.png')
print('second half decoded:', info1)

# composite colour + second-half-as-alpha
a = img1.convert('L').resize(img0.size)
out = img0.convert('RGB')
out.putalpha(a)
out.save('probe_composited.png')
print('wrote probe_mip0.png / probe_second.png / probe_composited.png')
