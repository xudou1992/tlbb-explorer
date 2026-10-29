# -*- coding: utf-8 -*-
"""生成 多怪锚点验证_20261007.md（表格从 compare_anchors.json 生成，避免转抄错数）。"""
import json

CJ = json.load(open(r"D:\TLGL\.scratch\multi_model\compare_anchors.json", encoding="utf-8"))
VAC = ["shoutao(对照)", "hmz_shoutao", "xiaobaishe", "duzhizhu", "xuanhaima", "bird", "buliandeng"]
ORDER = ["yifu(对照)", "hmz_yifu", "hmz_lian", "daheixiong", "daomuzei", "baolong",
         "jiuweihu", "lk_lian", "lk_yifu", "heihou"]

# ---- 大表（非空载模型逐行） ----
big = ["| 模型 | 动作 | 帧数 | A0 裸bind 帧均/全max | A1 逐动作f0 帧均/全max | A2 单锚 帧均/全max | 判定 |",
       "|---|---|---|---|---|---|---|"]
for tag in ORDER:
    r = CJ[tag]
    for a in sorted(r["rows"]):
        v = r["rows"][a]
        note = "（A1=A2）" if v["same_frame0_as_first"] else ""
        big.append("| %s | %s | %d | %.3f / %.3f | %.3f / %.3f | %.3f / %.3f | **%s**%s |" %
                   (tag, a, v["nf"], v["A0"][0], v["A0"][1], v["A1"][0], v["A1"][1],
                    v["A2"][0], v["A2"][1], v["verdict"], note))
BIG = "\n".join(big)

# ---- 空载表 ----
vac = ["| 模型 | 骨数 | 有权重骨 | root_only 占比 | 动作 | 全部行的 A0/A1/A2 位移 | 判定 |",
       "|---|---|---|---|---|---|---|"]
for tag in VAC:
    r = CJ[tag]
    w = r["rows"][sorted(r["rows"])[0]]
    same = all(abs(v["A0"][0] - x["A0"][0]) < 1e-9 and abs(v["A1"][0] - x["A1"][0]) < 1e-9
               and abs(v["A2"][0] - x["A2"][0]) < 1e-9 for x in r["rows"].values())
    vac.append("| %s | %d | %d | %.2f | %d | %.3f / %.3f（全部行同值=%s） | tie ×%d |" %
               (tag, r["NJ"], r["n_weighted_bones"], r["root_only_frac"], len(r["rows"]),
                w["A0"][0], w["A0"][1], same, len(r["rows"])))
VAC_T = "\n".join(vac)

# ---- 反例表 ----
losses = ["| 模型 | 动作（数据类） | A0 帧均/全max | A1 帧均/全max | Δ帧均 | Δ全max | 形态 |",
          "|---|---|---|---|---|---|---|"]
LOSS_META = {
    ("hmz_lian", "deadbegin"): ("deadbegin≡flyingdead", "双差", "马尾单骨远行：A1 帧0=0 → 末帧 3.781 单调增长"),
    ("hmz_lian", "flyingdead"): ("deadbegin≡flyingdead", "双差", "同上（同数据）"),
    ("daomuzei", "daomuzei_deadbegin"): ("deadbegin≡flyingdead", "仅帧均", "A1 帧0=0 → 末帧 1.995；全max 反而小 0.387"),
    ("daomuzei", "daomuzei_flyingdead"): ("deadbegin≡flyingdead", "仅帧均", "同上（同数据）"),
    ("daomuzei", "daomuzei_hit01"): ("hit01", "仅帧均", "峰值 1.512 vs 1.491（+1.4%），全max 反而小 0.088"),
    ("daomuzei", "daomuzei_hit03"): ("hit03", "双差", "峰值 1.258 vs 1.136；全max +0.185"),
    ("lk_yifu", "deadbegin"): ("deadbegin≡flyingdead", "仅帧均", "A1 帧0=0 → 末帧 2.406；全max 反而小 0.394"),
}
for tag in ORDER:
    r = CJ[tag]
    for a in sorted(r["rows"]):
        v = r["rows"][a]
        if v["verdict"] != "LOSS":
            continue
        cls, kind, morp = LOSS_META[(tag, a)]
        losses.append("| %s | %s（%s） | %.3f / %.3f | %.3f / %.3f | %+.3f | %+.3f | %s，%s |" %
                      (tag, a, cls, v["A0"][0], v["A0"][1], v["A1"][0], v["A1"][1],
                       v["A1"][0] - v["A0"][0], v["A1"][1] - v["A0"][1], kind, morp))
LOSS_T = "\n".join(losses)

# ---- 汇总表 ----
summ = ["| 模型 | 来源 | 骨数 | 有权重骨 | root_only | 动作 | 胜/平/负 | ΣA0帧均 | ΣA1帧均 |",
        "|---|---|---|---|---|---|---|---|---|"]
SRC = {
    "yifu(对照)": "npc/quest/w1351_monster_xiyuqiezei（复用 .scratch/glb_rigged）",
    "hmz_yifu": "npc/quest/w1351_monster_heimiaozhanshi（本班导出）",
    "hmz_lian": "npc/quest/w1351_monster_heimiaozhanshi（本班导出）",
    "daheixiong": "npc/quest/w1351_monster_daheixiong（本班导出）",
    "daomuzei": "npc/quest/w1351_monster_daomuzei（本班导出）",
    "baolong": "npc/quest/w1351_boss_baolong（本班导出）",
    "jiuweihu": "npc/quest/w1351_boss_jiuweihu（本班导出）",
    "lk_lian": "npc/quest/w1351_boss_likui（本班导出）",
    "lk_yifu": "npc/quest/w1351_boss_likui（本班导出）",
    "heihou": "npc/changjingdaoju/w1351_caiji_heihou_01（本班导出）",
}
for tag in ORDER:
    r = CJ[tag]
    s0 = sum(v["A0"][0] for v in r["rows"].values())
    s1 = sum(v["A1"][0] for v in r["rows"].values())
    summ.append("| %s | %s | %d | %d | %.2f | %d | %d/%d/%d | %.2f | %.2f |" %
                (tag, SRC[tag], r["NJ"], r["n_weighted_bones"], r["root_only_frac"], len(r["rows"]),
                 r["win"], r["tie"], r["loss"], s0, s1))
SUMM_T = "\n".join(summ)

DOC = """# 多怪锚点验证：frame0 锚跨怪复测（2026-10-07）

承接 `.scratch/ani_axis/锚点判定_20261007.md` §四的裁决「播放 = 逐动作 frame0 锚」。
该裁决当时的证据只有一只怪（yifu_001；shoutao_001 与它动画逐字节相同，实质单证据）。
本班把同一比对搬到 **14 只怪**上重做：13 只解出骨架（rigged 导出 15 份 GLB），
加复用的 yifu/shoutao 对照共 **17 份带动画 GLB** 进入比对（181 行）；
jiumozhi 骨架解不出，退出样本。回答一个决策问题：
**frame0 锚的优势是这副骨架的偶然，还是 .ani + .mesh 蒙皮格式的通例。**

仓库代码零改动。工具为冻结版（`cargo build --release --offline --jobs 1`，
构建时 git 工作树干净、无他人改动，exe 复制在 `.scratch/multi_model/bin/`）。

## 判定：🟢 成立（带一条已量化的限定）

**一句话：可判定的 10 只怪（28~136 骨、跨任务怪/兽形/Boss/采集物/挂件部件 6 个骨架族）
× 86 类独立动作数据（按 .ani 逐字节去重），逐动作 frame0 锚在 95.0% 的 (怪,动作) 行上
帧均位移优于裸 bind 锚；7 行反例（5 类数据）全部是「动作幅度」形态而非「撕裂」形态，
其中 5/7 行全帧最大位移仍以 frame0 锚更优；10/10 只怪在全程合计口径下无一只更适合裸 bind。
单锚对照（拿第一条动作的 frame0 播全部动作）跨怪同样不可用：dead 类动作帧均劣化 +0.5~+7.6。**

**限定**：反例不是零——「A1 行行赢」在别的怪上**不成立**（yifu 上 15/15 全胜是这只怪的运气：
它的 deadbegin 类动作幅度恰好小于 frame0-bind 失配）。落码时的自检断言不该用「行行赢帧均」，
应该用构造性恒等式「frame0 锚下第 0 帧蒙皮位移 == 0」（对任何怪任何动作严格成立，
能抓接线错误，不会误报动作幅度）。

## 一、样本与口径

### 1.1 冻结工具
`mesh2glb` / `skel_dump`（tlbb-explorer crates/core），构建于干净工作树，
exe 存 `.scratch/multi_model/bin/`。`IBM vs inv(node树bind世界)` 口径自洽：
可判定 10 模型最大差 ≤ 9.2e-06（jiuweihu）、其余 ≤ 6e-07；空载 buliandeng 1.9e-04
（对锚问题无影响，见 §二空载机制）。

### 1.2 样本清单（14 只怪）

| 怪 | 目录 | 结果 |
|---|---|---|
| xiyuqiezei | npc/quest/w1351_monster_xiyuqiezei | 对照组，复用 `.scratch/glb_rigged/` 现成 GLB ×2 |
| heimiaozhanshi | npc/quest/w1351_monster_heimiaozhanshi | 3 部件 rigged（lian 85 顶点/shoutao 41/yifu 411） |
| daheixiong | npc/quest/w1351_monster_daheixiong | rigged（兽形，443 顶点） |
| daomuzei | npc/quest/w1351_monster_daomuzei | rigged（786 顶点） |
| jiumozhi | npc/quest/w1351_boss_jiumozhi | **骨架解不出**（skel_dump：节点 0 个，但 .ani 有 77 骨 15 条）→ 静态导出，无蒙皮无动画，退出样本 |
| baolong | npc/quest/w1351_boss_baolong | rigged（719 顶点，61 骨） |
| jiuweihu | npc/quest/w1351_boss_jiuweihu | rigged（4479 顶点，136 骨，网格只绑 3 骨） |
| likui | npc/quest/w1351_boss_likui | 2 部件 rigged（lian 808/yifu 655） |
| xiaobaishe | npc/changjingdaoju/w1351_caiji_xiaobaishe_01 | rigged 但空载（153 顶点全绑根骨） |
| heihou | npc/changjingdaoju/w1351_caiji_heihou_01 | rigged（315 顶点，21 骨有权重） |
| duzhizhu | npc/changjingdaoju/w1351_caiji_duzhizhu_01 | rigged 但空载（406 顶点全绑根骨） |
| xuanhaima | npc/model/w1351_ani_model_pets_xuanhaima_idle02_h001 | rigged 但空载（2 骨） |
| ysym_bird | npc/model/w1351_ani_ysym_bird_h001 | rigged 但空载（3563 顶点全未覆盖→挂根骨） |
| buliandeng | npc/dynamic/w1351_mrsz_buliandeng_001 | rigged 但空载（动态物件） |

导出失败 0；唯一退出的是 jiumozhi（parse_hierarchy 解不出节点表）。

### 1.3 口径（照抄 k2_cross.py，只参数化路径）
- 播放局部轨道 → glTF 列向量 world = parent·local 原样复合（无任何 R 共轭）；
- **A0 裸 bind 锚** = GLB `skins[0].inverseBindMatrices`（= 现状导出口径）；
- **A1 逐动作 f0 锚** = `inv(world_frame0)`（每条动作自己的）；
- **A2 单锚对照** = 第一条动作（名字排序）的 f0 锚播全部动作；
- 位移 = `‖Vp(f) − POS‖`，mask = 非 root_only 且权重和 > 0.999（空载模型退化为全体顶点）；
- **帧均** = max-over-frames(帧内顶点均值)；**全max** = 全帧全局最大位移；
- 判定（主判据帧均，容差 1e-9）：A1 < A0 → WIN；= → tie；> → LOSS。
- **校准**：yifu 对照行的 A0/A1 数字与《锚点判定_20261007》§一表逐格一致
  （如 behit01 1.234/3.420 → 0.970/2.397；dead 1.708/3.771 → 0.002/0.029）。
  A2 列与本班用「名字排序第一条」（behit01）做单锚，旧档案用 idle01，数字略有差异，方向一致。

## 二、决定性大表（非空载 10 模型 × 140 行）

A2 一列里标（A1=A2）的行 = 该动作 frame0 与首条动作逐骨相同。

@@BIG@@

### 空载模型（7 份 GLB，41 行，无信息）

唯一有权重的骨都是 `000`（根骨）且**无轨道**（全帧世界 vs bind 最大 |Δt| = 0.000000），
蒙皮恒等：任何锚、任何动作位移都是 0。这些 (怪,动作) 对不携带锚点信息，剔出判定
（bird/buliandeng/xiaobaishe/duzhizhu 的导出 stderr 明示「覆盖顶点=0 未覆盖=全部」——
客户端 influence 表本来就没给这些网格逐骨权重）。

@@VAC@@

## 三、汇总

@@SUMM@@

- 非空载 140 行：**A1 胜 133（95.0%）、负 7（5.0%）、平 0**；
  全部 181 行（含空载 tie）：胜 133（73.5%）/ 平 41（22.7%）/ 负 7（3.9%）。
- 按独立动作数据（.ani 逐字节等价类，非空载模型）：**86 类中 81 类胜、5 类负（5.8%）**。
- Σ帧均（全程合计）：10/10 只怪 A1 显著优于 A0（1.5~3.7 倍），**没有一只怪整体更适合裸 bind**。

## 四、反例解剖（7 行 = 5 类数据，无一例外是「动作幅度」形态）

@@LOSS@@

**共同形态**（逐帧剖面见 `counter_analysis.txt`）：
1. A1 的帧0位移恒等于 0（构造性），反例动作的位移随帧**单调增长到末帧**
   （deadbegin 类：尸体从 frame0 姿态一路倒到地上，末帧帧均 1.995~3.781）——
   A1 把**真实动作幅度**记进了位移；yifu 的 deadbegin 也有同样的形状（帧均 1.558），
   只是幅度小于 A0 的常数撕裂才被判 WIN。
2. A0 的位移从帧 0 起就是一个**常数撕裂**（帧0 = 0.93~2.67 = frame0-bind 失配，全程不消失）。
3. 7 行反例里 5 行的**全max 仍以 A1 更优**（最坏顶点撕裂被 frame0 锚压低 0.09~0.39）；
   双指标都差的是 2 类数据（daomuzei_hit03：帧均 +0.122/全max +0.185；
   hmz_lian deadbegin 类：+0.170/+0.195，且发生在单骨马尾部件上）。
4. 反例与 frame0-bind 失配大小**无关**（daomuzei 输的 4 行 |Δt|=2.17，赢的 11 行同样
   span 1.19~2.19）；与骨骼数、体型、怪族也无关——只与「这条动作的末端离它的 frame0
   有多远」有关。

## 五、单锚对照（A2）：跨怪同样不可用

- 每只非空载怪都有动作 A2 显著劣化（A2 > A1 + 0.01 帧均）：yifu 5 行、hmz_lian 4、
  hmz_yifu 4、daheixiong 3、daomuzei 3、baolong 1、jiuweihu 2、lk_lian 1、lk_yifu 3、
  heihou 0（3 条 idle 逐字节同组，A2≡A1 属平凡）。
- **最差绝对劣化全部落在 dead / flyingdeadbegin（2 帧死亡）数据类**：
  A1 ≈ 0.000，A2 = +0.516（daheixiong）~ **+7.562（jiuweihu）** 帧均。
- 如实记：A2 在 6 行上反而小幅优于 A1（walk 类，最大 −0.117 帧均）——
  个别行更近不代表策略可用，dead 类的爆炸（0 → 7.6）否定单锚方案。
- 结论跨怪成立：**锚必须逐动作取**（或导出侧给每条动作独立 inverseBind）。

## 六、给 app 播放与 GLB 导出的建议

1. **播放落码**：逐动作 frame0 锚按本班证据可以落——证据从「单怪 15/15」升级为
   「10 怪 / 6 骨架族 / 86 类数据 95% 行胜 + 10/10 怪全程合计碾压」。实现同旧方案：
   three.js 侧逐动作重算 `skeleton.boneInverses = inv(world_frame0)`，或导出侧每条动作
   写独立 skin/IBM。
2. **限定条件（沿用旧档案 + 本班新增）**：
   - 连贯/不撕裂判据上 frame0 锚胜；**绝对朝向与半程相位仍是未证口径**（本班不改这条）。
   - deadbegin/flyingdead 类在 frame0 锚下整段可见「尸体远行」（末帧帧均 2.0~3.8）——
     这是真实动作幅度，不是 bug；裸 bind 的替代品在帧 0 就带 0.9~2.7 的常数撕裂。
   - 空载网格（7/17）锚选择无影响，两种实现都便宜。
3. **自检/闸门**：不要用「每行帧均 A1<A0」做闸门（5.8% 数据类天然反例）。
   用构造性恒等式 **「frame0 锚下第 0 帧蒙皮位移 == 0（顶点级，任意怪任意动作）」**
   做导出/播放的自检断言；再配一条聚合口径「全程 Σ帧均 A1 < A0」作为数据级回归闸门
   （本班 10/10 成立）。这两条在任何怪上都可自动验证。
4. **回闸门/新开口**：jiumozhi 型失败（.ani 77 骨 15 条俱全但 .mesh 解出 0 节点）
   是 exporter 的真实缺口，值得单开一班追（本班只如实记，不猜原因）。

## 七、文件清单（本班新增，均在 `.scratch/multi_model/`）

| 文件 | 内容 |
|---|---|
| `bin/mesh2glb.exe`、`bin/skel_dump.exe` | 冻结版工具（干净工作树构建） |
| `glb/m_*.glb`（16 份：15 rigged + jmz 静态）+ `glb/manifest_*.json`（13 份） | 14 只怪的导出与清单 |
| `glb/export_stderr_*.txt` | 每怪导出明细（覆盖顶点/无bind骨/未解轨道名） |
| `compare_anchors.py` / `.txt` / `.json` | 三锚 × 17 GLB × 181 行比对（口径照 k2_cross） |
| `counter_analysis.py` / `.txt` | 反例逐帧剖面、空载机制、同数据类折算、f0-bind 分野 |
| `build_archive.py` | 本档案生成器（表格直读 JSON，防转抄错数） |
| `多怪锚点验证_20261007.md` | 本档案 |
"""
DOC = DOC.replace("@@BIG@@", BIG).replace("@@VAC@@", VAC_T).replace("@@SUMM@@", SUMM_T).replace("@@LOSS@@", LOSS_T)
open(r"D:\TLGL\.scratch\multi_model\多怪锚点验证_20261007.md", "w", encoding="utf-8").write(DOC)
print("saved -> 多怪锚点验证_20261007.md, %d chars" % len(DOC))
