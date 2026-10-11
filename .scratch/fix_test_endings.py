# Edit 工具把整个 textureState.test.js 的行尾重排了（原文件 CRLF/LF 混用，226 行 167 个 CR，
# 改完变 241 个 CR），git diff 一下多出 135 行假变化。这里按字节退回原文件，再把新闸门
# 追加到末尾——追加块的行尾跟原文最后一行一致，diff 就只剩我真正加的那几条。
import subprocess
from pathlib import Path

P = Path("D:/TLGL/tlbb-explorer/app/tests/textureState.test.js")
orig = subprocess.run(["git", "-C", "D:/TLGL", "show", "HEAD:tlbb-explorer/app/tests/textureState.test.js"],
                      capture_output=True, check=True).stdout
nl = b"\r\n" if orig.rstrip()[-2:] in (b";\r", b"\r\n") or orig.endswith(b"\r\n") else b"\n"
tail = orig[-400:]
nl = b"\r\n" if tail.count(b"\r\n") >= tail.count(b"\n") - tail.count(b"\r\n") else b"\n"
print("末尾行尾判定：", "CRLF" if nl == b"\r\n" else "LF")

BLOCK = '''
// 2026-10-11 真窗口撞到的：下拉里塞了个不在清单上的值，旧写法 `|| slots.find(s=>!s.overrideHash)`
// 把标注静默写到了**另一条槽位**上（我选的槽没写进去，第一条未确认的反倒变 🟢）。
// 覆盖表是贴图线唯一的标准答案来源，标错一条比少标一条贵得多。
test("确认不许改标到别的槽位，选不中就什么都不写", () => {
  assert.equal(confirmTarget([SLOT_A, SLOT_B], SLOT_B.name).slot, SLOT_B, "选中谁就写谁");
  const miss = confirmTarget([SLOT_A, SLOT_B], "不在这儿的野值.tga");
  assert.equal(miss.slot, undefined, "对不上不该返回任何槽位");
  assert.ok(miss.reason.includes("什么都没写"), miss.reason);
  assert.equal(confirmTarget([SLOT_A, SLOT_B], null).slot, undefined, "没选槽位也不该乱写");
  const done = confirmTarget([{ ...SLOT_A, overrideHash: "aa" }, { ...SLOT_B, overrideHash: "bb" }], SLOT_A.name);
  assert.equal(done.slot, undefined, "全确认了要说明为什么点不动");
  assert.ok(done.reason.includes("撤销"), done.reason);
  assert.ok(confirmTarget([], SLOT_A.name).reason, "空清单也要给原因，不是静默 return");
});
'''.strip("\n").replace("\n", nl.decode()).encode("utf-8")

head = orig.replace(b'import { texBlock, texSlotsHtml, texCandidatesHtml, trialPick, uvMapHtml } from',
                    b'import { texBlock, texSlotsHtml, texCandidatesHtml, trialPick, uvMapHtml, confirmTarget } from')
assert head != orig, "import 行没替换成功"
# 原文里那条 test 名字保持与提交信息一致；把新块接在文件末尾。
out = head.rstrip(b"\r\n") + nl + nl + BLOCK
P.write_bytes(out)
print("字节前缀核对：", "原内容未被重排" if out.startswith(head[:200]) else "★前缀变了")
print("CR 数：原", orig.count(b"\r"), "现", out.count(b"\r"))
