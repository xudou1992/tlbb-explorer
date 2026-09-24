# v0.1-mesh-browser · 里程碑基线（2026-09-23 17:0x 冻结）

这个仓库不是 git 仓库，打不了真 tag，所以把基线写成文件：**这一批产物的数字与复现命令**。
后面做骨骼/地图实验时，以这份为准回退。

## 这一版有什么

| 能力 | 位置 | 实测 |
|---|---|---|
| `.mesh` 几何全量解析（含多材质槽） | `tlbb-explorer/crates/core/src/preview/geometry.rs` `parse_mesh` | 7,996 / 7,996 成功，0 失败 |
| 顶点流拆解（法线 / 第一套 UV / 面级表） | 同上 | 法线 7,891 · UV 7,169 · 面级表 1,651 |
| 双实现对账闸门 | `crates/core/src/bin/mesh_gate.rs` + `.scratch/agent_glb_crosscheck.py` | 逐字段 **0 分歧** |
| glTF 2.0 导出 | `crates/core/src/export/gltf.rs` | 单测 3 条绿 |
| 批量导出 | `crates/core/src/bin/mesh2glb.rs` | 7,712 个 .glb / 281MB / 10 秒（284 个重复内容合并） |
| 官方校验器 | npm `gltf-validator` | 抽 200 个：**0 error / 0 warning** |
| 网页浏览台 | `D:\TLGL\web-viewer\`（three.js 0.169） | 小图 24/24 真渲染；详情页 `readPixels` 24,082 亮像素、明暗 27–187 |
| 规模 | `web-viewer/model/manifest.json` | 745 万顶点 / 740 万三角面；分类：地图资源 3,264 · NPC 与怪物 2,815 · 特效模型 1,700 · 玩家角色 217 |

## 复现

```powershell
cd D:\TLGL\tlbb-explorer
cargo test -p tlbb-core                                   # 单元/集成测试
cargo build -p tlbb-core --release --bin mesh_gate --bin mesh2glb
.\target\release\mesh_gate.exe "D:\TLGL\.scratch\out\tree" "D:\TLGL\.scratch\agent_glb_mesh.tsv"
python D:\TLGL\.scratch\agent_glb_crosscheck.py           # 看 field disagreements : 0
.\target\release\mesh2glb.exe                             # 重导 7,712 个 .glb + manifest
node D:\TLGL\web-viewer\serve.mjs                          # http://127.0.0.1:8090/
```

## 这一版**故意**没有做的（都是数据决定，不是偷懒）

- **花纹/贴图**：2.4 万张贴图在客户端里被剥掉路径，只有约 2,259 张界面图有名字，接不上；
  所以 glb 只有 `baseColorFactor`，`mesh` 里没有贴图二进制。贴图状态一律标"未定位"，不标"缺失"。
- **姿势与动画**：蒙皮权重**证实不在** `.mesh`（穷举打分最高 0.086＝噪声）也不在 `.ske`
  （字符串表后只剩 0/4 字节，四元数样窗口 1629/1630 文件为 0）。引擎是 GPU 蒙皮
  （`BlendIndices`/`BlendWeight` + `BoneMatrixParameters` 常量缓冲），权重来源还没定位。
- **骨骼线框**：数据在 `.mesh` 索引之后的尾部节点表里（32B/条：父级 + 名字；另有 `name[32] + 4×4` 记录），
  表头语法没闭环 —— 这是 v0.4 的活，比追权重近。

## 已知未完成项（工作台侧，属另一会话的文件）

`app/web/lib/detailState.js` 的 `s.mesh.visible = meshes.length > 0` 会让立体面板在
11,035 / 13,080 个资产组（**84.4%**）里静默消失且零提示——这就是用户说的"只能看到骨骼那一行"。
补丁已备好：`.scratch/agent_p0_静默消失_补丁.md`（因并发写会静默互相覆盖，等对方会话收工再落）。
