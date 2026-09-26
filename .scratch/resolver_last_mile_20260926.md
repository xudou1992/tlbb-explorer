# Texture Resolver · 最后一公里战报 · 2026-09-26

> 一句话：**引擎的名字指纹被破译了**——`sdbm32(小写全路径) = pak 索引哈希高 32 位`，
> 57,274 个已知配对 100% 命中、全库 105,327 条零冲突。cfg×指纹联动直接点名 46,863 个
> pak 条目（含白捡 4,780 个匿名件）。但 24,260 张运行时贴图被证实**故意无路径编址**，
> 它们的挂接只能走证据链（内容特征+UV+人工）——这正是四梯队设计要吃的最后一段。

## 1. 引擎指纹（本日最大收获，可进 core）

```
pak_hash_u64 = ( sdbm32( path.to_lowercase().replace('\\','/') ) << 32 ) | 低32位(未解,不影响)
```

- 验算：42,083 条 cfg∩db 路径 sdbm32 → high32 全中（5000 抽样 5000）。
- 唯一性：105,327 条目 high32 **零冲突** → 按 high32 查找即确定性定位，低 32 位
  （≠filecrc，函数未解）不影响查找。
- 立即收益：cfg 72,764 路径 → **42,083 命中已命名条目 + 4,780 命中匿名条目**
  （TerrainInfo / mapref / tiny .scene 等地图件白捡身份）；25,901 条路径不在 pak
  （源资产被剥离，见 §2）。

## 2. 三条"确定性挂接"路线全部试完（贴图除外都通）

| 路线 | 结果 |
|---|---|
| 源路径变体哈希（20 种：换扩展/去前缀/反斜杠/大写/裸名…）× 11,851 tga | 全灭（≈噪声级命中）→ **运行时贴图不是按源路径编的址** |
| JMT1 文件头内嵌名 | 无。24B 头（JMT1+tag+marker+declared+w/h/mips）+ mip 表直接进块数据，没有名字区 |
| global.jstr（15.5MB，本日新解格式） | 已全解：`[JSTR][u32]['%SiG'+8B][u32 count=297,278][count×(u32 len,u32 hash)][NUL 结尾字符串区]`。内容=游戏全局字符串池（lua/pu/mdl/…/tga 17,546 条引用路径）。其存哈希与 pak 指纹无关 → 是**引用清单不是映射表** |

旁证：`out/tree/data/effect/textures/fire/` 等目录里只有同名 `.mtl`（材质在），cfg 承诺的
`.tga` 在盘上和 pak 里都不存在——**源 tga 是打包时剥离的美术资产，pak 里的匿名贴图是
重新编址的运行时版本**。

## 3. 结论：贴图挂接 = 四梯队②③④，工程路线已定

cfg 路径虽然指不到字节，但它给了**语义目录**（`data/source/npc/quest/<角色>/texture/`、
`data/effect/textures/fire/`），加上贴图人群先验（§4），候选池能从 24,260 缩到几十：
锚定（cfg 路径语义 + codec/尺寸/mips 先验）→ UV 试贴打分 → 人工确认 → 证据等级入库。

## 4. 匿名贴图人群先验（配对原料）

- 尺寸：64×64 13,457 · 256×256 4,480 · 1024×1024 2,361 · 512×512 1,152（2 的幂 99.3%）
- codec：RGBA32 12,726 · BC3 9,752 · BC1 1,782（与有名 WEBP 图标人群零重叠）
- 内容唯一性：distinct filecrc 24,239/24,261（仅 22 重复块）
- 解码失败仅 1 张；缩略图 24,260 张在 TEMP 可按 hash join

## 5. 顺带战果

- 4,780 个匿名 pak 条目获得路径身份（地形/格子/杂件），可作为 sidecar 名字表落盘。
- JSTR 格式全解（297,278 串）——后续做"游戏实际引用清单"校验层有它就够。
- geom 12,676 块只有 6 种固定尺寸（105,853~109,960B）——模板化数据，身份继续挂起。

## 复现

```bash
python D:/TLGL/.scratch/hash_hunt.py       # 指纹函数验算
python D:/TLGL/.scratch/resolver_probe.py  # cfg 路径 × pak 指纹全量对账
python D:/TLGL/.scratch/variant_hunt.py    # 变体全灭记录
python D:/TLGL/.scratch/jstr_final.py      # JSTR 全解
python D:/TLGL/.scratch/cfg_final3.py      # cfg 仲裁（见 cfg_arbitration_20260926.md）
```
