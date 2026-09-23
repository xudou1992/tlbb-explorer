import subprocess, re

EXE = r'D:\TLGL\.scratch\rc3\debug\view.exe'
r = subprocess.run([EXE, "--name=w1351_model_xianglong_b7_lf001_E.mesh", "--dump=18532"],
                   capture_output=True, timeout=120)
txt = r.stdout.decode('cp936', errors='replace')

# reconstruct bytes from hex dump lines
buf = bytearray()
for line in txt.splitlines():
    m = re.match(r'^  ([0-9a-f]{6})  (.{48}) (.*)$', line)
    if not m:
        continue
    hexregion = m.group(2).replace(' ', '')
    for i in range(0, len(hexregion), 2):
        try:
            buf.append(int(hexregion[i:i+2], 16))
        except ValueError:
            pass

print("reconstructed bytes:", len(buf))

# printable-string extraction >=4 containing a dot
runs = []
cur = bytearray()
for c in buf:
    if 0x20 <= c <= 0x7e:
        cur.append(c)
    else:
        if len(cur) >= 4:
            runs.append(bytes(cur).decode('ascii'))
        cur = bytearray()
if len(cur) >= 4:
    runs.append(bytes(cur).decode('ascii'))

refs = [s for s in runs if '.' in s and re.search(r'\.(tga|mtl|dds|mdl|ske|ani|png|bmp)$', s, re.I)]
print("runs with dot & known ext:", len(refs))
for s in refs:
    print("  ", s)
print("\n--- all runs >=6 ---")
for s in runs:
    if len(s) >= 6:
        print("  ", s)
