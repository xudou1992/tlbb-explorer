import re

EXE = r'D:\TLGL\.scratch\rc3\debug\view.exe'
import subprocess
r = subprocess.run([EXE, "--name=w1351_model_xianglong_b7_lf001_E.mesh", "--dump=18532"],
                   capture_output=True, timeout=120)
txt = r.stdout.decode('cp936', errors='replace')
buf = bytearray()
for line in txt.splitlines():
    m = re.match(r'^  ([0-9a-f]{6})  (.{48}) (.*)$', line)
    if not m:
        continue
    hexregion = m.group(2).replace(' ', '')
    for i in range(0, len(hexregion), 2):
        try: buf.append(int(hexregion[i:i+2], 16))
        except ValueError: pass

def wide(sig):
    # find UTF-16LE sequences of ascii letters/dots of len>=4 with a dot
    pat = sig.encode('utf-16-le')
    out = []
    idx = 0
    while True:
        j = bytes(buf).find(pat, idx)
        if j < 0: break
        # extend backward/forward to grab the whole wide string
        s = j
        e = j
        # backward
        k = j
        while k >= 2 and 0x20 <= buf[k-2] <= 0x7e and buf[k-1] == 0:
            k -= 2
        # forward
        k2 = j + len(pat)
        while k2+1 < len(buf) and 0x20 <= buf[k2] <= 0x7e and buf[k2+1] == 0:
            k2 += 2
        w = bytes(buf[k:k2]).decode('utf-16-le', errors='replace')
        out.append(w)
        idx = k2
    return out

for ext in ['.tga', '.mtl', '.dds', '.mdl', '.ske', '.ani', '.png']:
    ws = wide(ext)
    if ws:
        print(ext, "->", ws[:20])
print("scan done")
