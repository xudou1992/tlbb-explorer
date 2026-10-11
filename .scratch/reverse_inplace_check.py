# 反向验红：把「确认」退回整页重刷（showDetail），新加的三条原地更新闸门必须变红。
# 跑完按字节还原并自检 md5。
import hashlib
import subprocess
from pathlib import Path

P = Path("D:/TLGL/tlbb-explorer/app/web/detail.js")
orig = P.read_bytes()
start = orig.index(b"    // \xe5\x8f\xaa\xe9\x87\x8d\xe7\x94\xbb\xe6\xa7\xbd\xe4\xbd\x8d\xe6\xb8\x85\xe5\x8d\x95")
end = orig.index(b'    return;\n  }\n  if (b.dataset.act === "clear")')
old = orig[start:end]
back = b"    showDetail(texGid || state.selected);\n"
assert b"slot.overrideHash = c.hash" in old, "要替换的块里没有原地更新的代码，先核对"

try:
    P.write_bytes(orig[:start] + back + orig[end:])
    r = subprocess.run(
        ["node", "--experimental-vm-modules", "--test", "--test-name-pattern",
         "确认不许改标到别的槽位", "tests/behavior.test.js"],
        cwd="D:/TLGL/tlbb-explorer/app", capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    red = "fail 1" in r.stdout or "not ok" in r.stdout
    out = []
    for line in r.stdout.splitlines():
        if "not ok" in line or "AssertionError" in line or "2.8" in line or "只剩撤销" in line:
            out.append(line.strip()[:120])
    Path("D:/TLGL/.scratch/reverse_inplace.txt").write_text(
        f"退回整页重刷后闸门变红：{red}\n" + "\n".join(out), encoding="utf-8")
finally:
    P.write_bytes(orig)
    now = P.read_bytes()
    Path("D:/TLGL/.scratch/reverse_inplace.txt").write_text(
        Path("D:/TLGL/.scratch/reverse_inplace.txt").read_text(encoding="utf-8")
        + f"\n还原 md5 一致：{hashlib.md5(now).hexdigest() == hashlib.md5(orig).hexdigest()}",
        encoding="utf-8")
print(open("D:/TLGL/.scratch/reverse_inplace.txt", encoding="utf-8").read())
