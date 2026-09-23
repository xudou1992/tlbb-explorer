import subprocess, os, re, sqlite3, struct

EXE = r"D:\TLGL\.scratch\rc3\debug\view.exe"
ENV = dict(os.environ)

def dump_bytes(name):
    p = subprocess.run([EXE, "--name=" + name, "--dump=99999999"],
                       capture_output=True, cwd=r"D:\TLGL", env=ENV, timeout=600)
    o = p.stdout.decode("utf-8", "replace")
    hexes = []
    for line in o.splitlines():
        m = re.match(r"\s*([0-9a-f]{6})\s+((?:[0-9a-f]{2} ){1,16})", line)
        if m:
            off = int(m.group(1), 16)
            vals = bytes(int(x, 16) for x in m.group(2).split())
            assert off == len(hexes), (off, len(hexes))
            hexes.extend(vals)
    return bytes(hexes)

con = sqlite3.connect(r"D:\TLGL\.scratch\resources.db")
c = con.cursor()
c.execute("""SELECT name, original FROM resources WHERE ext='.mesh' AND coalesce(name,'')<>''
             ORDER BY original ASC LIMIT 4""")
small = c.fetchall()
c.execute("""SELECT name, original FROM resources WHERE ext='.mesh' AND coalesce(name,'')<>''
             ORDER BY original DESC LIMIT 2""")
big = c.fetchall()
con.close()
print("small:", small, file=open(r"D:\TLGL\.scratch\mesh_sel.txt", "w", encoding="utf-8"))
print("big:", big, file=open(r"D:\TLGL\.scratch\mesh_sel.txt", "a", encoding="utf-8"))

samples = [("w1351_monster_xiyuqiezei_yifu_001.mesh", 0)] + small + big

blocks_report = []
saved = {}
for name, _ in samples:
    try:
        data = dump_bytes(name)
    except Exception as e:
        blocks_report.append("%s DUMP FAIL %s" % (name, e))
        continue
    saved[name] = data
    open(r"D:\TLGL\.scratch\meshbin_%s.bin" % name.replace('/', '_'), "wb").write(data)
    # scan for 4CC ASCII block tags after the 0x8C header
    tags = []
    for i in range(0x8C, len(data) - 4):
        w = data[i:i+4]
        if all(0x41 <= b <= 0x5a or 0x30 <= b <= 0x39 for b in w) and len(set(w)) >= 2:
            if not tags or tags[-1][0] < i - 8:
                tags.append((i, w.decode()))
    # collapse: keep first occurrence of each tag with offsets
    seen = {}
    for off, t in tags:
        if t not in seen:
            seen[t] = off
    blocks_report.append("%s size=%d tags(first-off)=%s" % (name, len(data), seen))

open(r"D:\TLGL\.scratch\mesh_blocks.txt", "w", encoding="utf-8").write("\n".join(blocks_report))
print("done", len(saved))
