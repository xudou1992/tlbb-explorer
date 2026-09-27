import os, hashlib

OUT = r"D:\TLGL\.scratch\scene_final.txt"
lines = []

BIN = r"D:\TLGL\tlbb-explorer\crates\core\src\bin"
SAM = r"D:\TLGL\tlbb-explorer\crates\core\tests\scene_samples"

lines.append("=== crates/core/src/bin ===")
for n in sorted(os.listdir(BIN)):
    fp = os.path.join(BIN, n)
    lines.append(f"  {n:<28} {os.path.getsize(fp):>8}")

lines.append("\n=== crates/core/tests/scene_samples ===")
for n in sorted(os.listdir(SAM)):
    fp = os.path.join(SAM, n)
    h = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    lines.append(f"  {n:<28} {os.path.getsize(fp):>8}  sha256={h}")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("done")
