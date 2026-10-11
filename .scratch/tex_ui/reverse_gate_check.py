# 反向验红：把 detail.js 退回旧写法（选不中就写第一条未确认 + 照 state.selected 重刷），
# 新加的接线闸门必须变红；跑完立刻按字节还原，还原后用 md5 自检。
import hashlib
import subprocess
from pathlib import Path

P = Path("D:/TLGL/tlbb-explorer/app/web/detail.js")
NEW = """    const chosen = confirmTarget(slots, pick ? pick.value : null);
    if (chosen.reason) {
      el("texNote").textContent = chosen.reason;
      return;
    }
    const slot = chosen.slot;""".encode()
OLD = """    const slot = (pick && slots.find((s) => s.name === pick.value)) || slots.find((s) => !s.overrideHash);""".encode()
RAW = """showDetail(texGid || state.selected);""".encode()
BACK = """showDetail(state.selected);""".encode()

orig = P.read_bytes()
assert NEW in orig and RAW in orig, "新写法不在文件里，先核对着再退"
muted = orig.replace(NEW, OLD).replace(RAW, BACK)
try:
    P.write_bytes(muted)
    r = subprocess.run(
        ["node", "--experimental-vm-modules", "--test", "--test-name-pattern", "确认不许改标到别的槽位",
         "tests/behavior.test.js"],
        cwd="D:/TLGL/tlbb-explorer/app", capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("旧写法下的接线闸门（该是红）：", "fail 1" in r.stdout or "not ok" in r.stdout)
    for line in r.stdout.splitlines():
        if "not ok" in line or "AssertionError" in line or "fail" in line:
            print("  ", line.strip()[:150])
finally:
    P.write_bytes(orig)
    back = P.read_bytes()
    print("还原自检 md5：", hashlib.md5(back).hexdigest(), "与原文件一致" if back == orig else "★不一致，立刻手工修")
