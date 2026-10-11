# README.md 是 CRLF/LF 混的行尾，Edit 把改动区整块归成了 CRLF，多出 13 行假变化。
# 这里从上一个提交取原始字节，只在两处锚点上做替换，新行一律用 \r\n，然后自检 diff 规模。
import subprocess
from pathlib import Path

F = "README.md"
prev = subprocess.run(["git", "-C", "D:/TLGL", "show", f"HEAD~1:{F}"], capture_output=True, check=True).stdout

A1 = "- ❌ 100% 自动恢复原始文件名不成立 —— 但**所属关系（贴图→材质→模型）可以重建**，见下面三层账第 3 层\r\n"
N1 = (
    "- ❌ 100% 自动恢复原始文件名不成立；**「所属关系可以重建」这句也要收窄**（2026-10-11 改准）：\r\n"
    "  能确定重建的只有「材质 → 它点名的贴图**名**」（`ResourcePath.cfg` 解释 90.8%）；\r\n"
    "  而「贴图名 → 包里那张贴图**字节**」这一环机器侧**一条边都没有**（六条桥证伪，见\r\n"
    "  `.scratch/tex_归属证据缺失_20261010.md`），所以四梯队的 ①②③ 只出候选排序、不出归属结论，\r\n"
    "  结论只能来自 ④ 人工确认或运行时挂钩。见下面三层账第 3 层\r\n"
).encode("utf-8")
A1b = A1.encode("utf-8")
assert prev.count(A1b) == 1, "锚点一没找到（行尾可能不是 CRLF，先看原文件）"

A2 = "   之前解析失败是因为字符串数 145,528 超了 `jbcf::parse` 的 8192 上限，文件本身无畸形。\r\n"
N2 = (
    "   之前解析失败是因为字符串数 145,528 超了 `jbcf::parse` 的 8192 上限，文件本身无畸形。\r\n"
    "   **四梯队 ①②③ 的定位改了（2026-10-11 改准）**：① 材质引用重解析这条桥已试完并否掉——\r\n"
    "   源 `.tga` 在打包时被剥离、运行时贴图块重新编址，材质点名的名字进不到包内那一格；\r\n"
    "   ② 内容特征与 ③ UV 吻合度只能产出「谁更像」的**排序**，产不出归属结论，所以在拿到 ④ 的标注之前\r\n"
    "   阈值、退化带、兜底层次**不可能自动校准**（校准的是排序，而排序对不对无参照）。\r\n"
    "   ④ 那一头 2026-10-11 把单价降到了 ~0.12 秒一条（确认只重画槽位清单，不再整页重解 20 张图），\r\n"
    "   覆盖表现在还是 `{\"overrides\": {}}`——等的是有人来标，不是再写代码。\r\n"
).encode("utf-8")
A2b = A2.encode("utf-8")
assert prev.count(A2b) == 1, "锚点二没找到"

out = prev.replace(A1b, N1).replace(A2b, N2)
Path("D:/TLGL/" + F).write_bytes(out)
print("CR 数：上提交", prev.count(b"\r"), "现在", out.count(b"\r"), "本次新增行", out.count(b"\n") - prev.count(b"\n"))
