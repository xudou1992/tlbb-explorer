# textureState.test.js 是 CRLF/LF 混合行尾（167 CR / 226 行），按记忆里那条规矩不能用 Edit：
# 这里按字节改 import 行 + 追加两条闸门，追加块用「文件最后一行的行尾」，跑完自检 CR 增量。
from pathlib import Path

P = Path("D:/TLGL/tlbb-explorer/app/tests/textureState.test.js")
raw = P.read_bytes()
old_imp = b'import { texBlock, texSlotsHtml, texCandidatesHtml, trialPick, uvMapHtml, confirmTarget } from'
new_imp = b'import { texBlock, texSlotsHtml, texCandidatesHtml, trialPick, uvMapHtml, confirmTarget, autoSlotForMesh } from'
assert raw.count(old_imp) == 1, "import 锚点不对"
out = raw.replace(old_imp, new_imp)

tail = raw[-120:]
nl = b"\r\n" if tail.count(b"\r\n") >= (tail.count(b"\n") - tail.count(b"\r\n")) else b"\n"
BLOCK = '''
test("autoSlotForMesh：只认「槽位与网格同名」，匹不上就返回 null，不硬猜一条", () => {
  assert.equal(autoSlotForMesh("a_yifu_001.mesh", [SLOT_A, SLOT_B]), SLOT_A.name);
  assert.equal(autoSlotForMesh("A_YIFU_001.MESH", [SLOT_A, SLOT_B]), SLOT_A.name, "大小写不该影响同名判定");
  assert.equal(autoSlotForMesh("a_shoutao_001.mesh", [SLOT_A, SLOT_B]), SLOT_B.name);
  assert.equal(autoSlotForMesh("b.mesh", [SLOT_A, SLOT_B]), null, "没有同名槽位就别假装认得");
  assert.equal(autoSlotForMesh("", [SLOT_A]), null);
  assert.equal(autoSlotForMesh("x.mesh", []), null);
  assert.equal(autoSlotForMesh("x.mesh", [{ name: null }]), null, "槽位缺名字也不能崩");
});

test("每份榜的下拉各自对准自己那份网格的同名槽；匹不上就把话写在脸上", () => {
  const html = texCandidatesHtml({ ...GROUP, mesh: "a_yifu_001.mesh", candidates: [CAND(1)] },
    [SLOT_A, SLOT_B], 0, 2);
  assert.ok(html.includes(`value="${SLOT_A.name}" selected`), html);
  assert.ok(html.includes("已对准与网格同名的槽"), html);
  const none = texCandidatesHtml({ ...GROUP, mesh: "z.mesh", candidates: [CAND(1)] },
    [SLOT_A, SLOT_B], 0, 2);
  assert.ok(!/selected/.test(none), "匹不上就不该有 selected");
  assert.ok(none.includes("这条得自己选"), none);
});
'''.strip("\n")
body = BLOCK.replace("\n", ("\r\n" if nl == b"\r\n" else "\n")).encode("utf-8")
out = out.rstrip(b"\r\n") + nl + nl + body + nl
P.write_bytes(out)
print("追加块行尾：", "CRLF" if nl == b"\r\n" else "LF")
print("CR 数：原", raw.count(b"\r"), "现", out.count(b"\r"), "| 行数增量", out.count(b"\n") - raw.count(b"\n"))
