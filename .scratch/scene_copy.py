import os, shutil, hashlib

SRC = r"C:\Users\Administrator\AppData\Local\Temp\tlbb_scene_samples"
DST = r"D:\TLGL\tlbb-explorer\crates\core\tests\scene_samples"
OUT = r"D:\TLGL\.scratch\scene_copy.txt"

NAMES = ["grid_749.scene", "grid_753_overstated.scene", "grid_753_with_tail.scene"]

lines = []
os.makedirs(DST, exist_ok=True)

for n in NAMES:
    s = os.path.join(SRC, n)
    d = os.path.join(DST, n)
    if not os.path.exists(s):
        lines.append(f"MISSING SRC {s}")
        continue
    if os.path.exists(d):
        lines.append(f"WARN target exists, will overwrite: {d}")
    shutil.copyfile(s, d)
    st = os.stat(d)
    h = hashlib.sha256(open(d, "rb").read()).hexdigest()
    hs = hashlib.sha256(open(s, "rb").read()).hexdigest()
    lines.append(f"{n}\n  src={s}\n  dst={d}\n  bytes={st.st_size}\n  sha256={h}\n  src_sha256={hs}\n  identical={h == hs}")

lines.append("\n=== dir listing ===")
for n in sorted(os.listdir(DST)):
    fp = os.path.join(DST, n)
    lines.append(f"  {n}  {os.path.getsize(fp)}")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("done")
