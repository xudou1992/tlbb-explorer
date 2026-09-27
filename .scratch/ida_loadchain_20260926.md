# 引擎加载链战报（IDA 定点打）· 2026-09-26

> 一句话：**pak 键公式补全为完整 64 位且 57,274 金标准 100% 全中；从 Game.exe 反汇出
> 完整加载链（GetFileID → 链接表重定向 → 40 字节条目二分）；`version_dx11.collect.pcfg`
> 格式全解，证实它是打包器的 ID 宇宙（cfg 72,764 路径 100% 在池）；并以 64 位精确公式
> 把「名字→匿名贴图」的**全部**出货字符串源测尽 = **零映射**。断开的根源是打包器用
> 「从未出货的源路径哈希」给运行时贴图编址——四梯队②③④是唯一通路，IDA 阶段使命完成。**

IDA 数据库：`D:\TLGL\tlbbgl_x64.exe.i64`（43,623 函数；本次已命名 20 个关键函数并保存）。

---

## 1. pak 键公式 —— 补全并钉死（可进 core）

```
norm(c)  : 'A'-'Z' → +32；'\\' → '/'；其余不变；字节按【有符号 char】参与运算
high32   = sdbm32 :  h = 0;      h = c + 65599*h
low32    = xorhash:  h = 0x4E67C6A7;  h ^= c + (h<<5) + (h>>2)
pak_key  = (high32 << 32) | low32
```

- 反汇出处：`pak_dualhash_sdbm_in_HIGH` (0x14059FA30) 与 `pak_dualhash_sdbm_in_LOW`
  (0x140313AB0)（同一对哈希、两种打包顺序；后者被转换缓存 `%s%016llx.dat` 使用）。
- **实测：57,274 个有名条目 100% 全中（高 32 位、低 32 位、完整 64 位各 57,274/57,274）**。
- 之前「低 32 位未解、≠filecrc」悬案就此关闭：低 32 位是种子 0x4E67C6A7 的 xor-sdbm 变体。
- 有符号 char 细节：GBK 高位字节按负数参与——Python 复算必须 `(c - 256 if c >= 128)`。

## 2. 完整加载链（全部 RTTI 实名）

```
材质里的贴图名(字符串)
  └─ FileSystem::GetFileID (0x1405A21A0)
       ├─ 普通模式：双哈希(path)
       └─ 更新模式(+144==7 且 infix 串非空)：拼装哈希(0x14059FAB0)
            = H(最后一个'.'前的部分 + '.' + FileSystem+96串 + 剩余部分)
  └─ FileSystem::OpenReadFile (0x14059FE70, 5 种模式)
       └─ case 0（包内读）：先查 FileLinkManager 链接树（ID→ID 重定向）
            ├─ 树 miss → 平铺数组二查 (0x1405A3740)
            └─ PackageManager::OpenReadFile (0x1405A68A0)
                 ├─ FindIndexEntry (0x1405A4A70)：三级查找 =
                 │    两棵覆盖树 + 【40 字节条目有序数组二分】[u64 键][32B 记录]
                 ├─ 记录字段（日志串实录）：uCrc/uFileCrc/uOffset/uSize/
                 │    uOccupiedSize/uFileSize/usVersion；旗标字节：
                 │    bit0=带名字前缀头(跳 len+17 字节) bit2=需转换 bit3=有解码密钥
                 └─ Compresser_Decompress (0x1405B5660) → MemoryFile/PackagedFile
  └─ 全部失败 → 外部文件回退 (access())
```

类名（RTTI）：`FileSystem::LogManager / FileLinkManager / PackageManager / UpdateManager /
MemoryFile / PackagedFile / AsynchronismReadPackagedFile / PackageConfigFileReader`。

挂载：`GameFileSystem::Mount` (0x140117D70)，每卷一个 0x188 字节对象；pcfg 文件名 =
`"version_" + 版本串 + [".collect"] + ".pcfg"`（game.log 实证：**version_dx11.collect.pcfg**）。

## 3. version_dx11.collect.pcfg 全解（PackageConfigFileReader，0x1405A3B30）

两份落盘：`.scratch/out/named/data__version_dx11.collect.pcfg`（6,681,714B，池 368,806）
与 `data_1__…`（7,521,146B，池 414,450）。

```
[u32 N]                                  ← ID 池容量（读满验证通过）
[u16 outer] 分组计数区：
    每层 [u16 标记] + 计数（u16，0xFFFF 转 u32）
    ★ 计数语义：只在「上一次计数 > 1」时才写——即"为 1 时省略"（setnbe 旗标）
      （第一次实现按"仅首组读"解析 → 只读出 39,172/368,806；修正后读满 N ✓）
池记录 × N：[u64 ID][u32 偏移][u16 ver(=1)][u8 卷号]   ← 原始母版布局
链接对区：[u32 frm][计数][计数 × u32 to]（同样的"为 1 省略"旗标）
尾部清单段（运行时不读，见 §5）：[包ID u64][元数据][计数][0xFFFF][有序成员池索引 × N]
```

### 池 = 打包器的 ID 宇宙（对账结果）

| 口径 | data.pak 版 | data_1 版 |
|---|---|---|
| 池容量 N | 368,806 | 414,450 |
| ∩ cfg 72,764 路径 | **72,764（100%）** | 72,764（100%） |
| ∩ 有名 57,274 | 56,134 | **57,274（100%）** |
| ∩ 匿名 pak 键 | 47,797 | 42,781 |
| 包外 ID（无串可考） | ~26.5 万 | ~31.4 万 |

池记录的 (偏移,卷号) 是**原始母版**的：vol↔pak 多对多（vol4→data3/data/data_1…），
与当前 6 个 pak 的 offset 对不上（0/56,134）——当前卷是重排过的，位置字段不可用。

### 链接对 = 多对一别名，与贴图无关

8,480（data 版）/9,636（data_1 版）条；大量「多个旧 ID → 同一个新 ID」的别名形态；
键/值双方 90% 是包外 ID；cfg 贴图路径只有 11 条出现在键侧。**不是贴图映射**。

### 尾部清单段（部分解）

组 = `[包ID u64][u16 a][u16 b][u32 X][u32 Y][u32 0][u32 成员数][0xFFFF][有序成员池索引×N]`。
- 实证组 1：包 ID = 一个**匿名 pak 条目**，成员 = 4 个 settings 文件（TextFilter 等）
  → 匿名条目可以是「捆绑包」。
- 大量组的成员同时含 cfg 源路径 ID（51,691 处，其中 tga 6,206 处）和匿名贴图键的池索引
  （19,670 处）；但**包 ID 本身既非 pak 键也非池 ID**（第三 ID 空间）。
- 运行时不读这段：`FileLinkManager::Load` 读完链接对即关闭文件（0x1405A4065 收尾），
  池数组也是局部分配、用完即 free——**尾部清单是打包工具残留，不是运行时数据**。

## 4. 运行时贴图加载行为（IDA 实录）

- `Texture_LoadByName_tga_fallback` (0x140722750)：按名加载失败 → **砍掉最后一个'.'后的
  部分 + ".tga" 重试**（引擎只有这一层名字变换）。
- `Lightmap_BuildNames_dds` (0x14060B5E0)：光贴图 = `"lightmap/" + 名字 + ".dds"`
  （含 "Shadow" 的用 ".tga"）。
- `ConvertCache_BuildName_rev_hash` (0x140318CD0)：纹理转换缓存文件名 = `%s%016llx.dat`，
  用**反装双哈希**（sdbm 在低 32 位）。
- 材质 (.mtl) 576B 全量人工判读：只有贴图名字符串与 sfl 字段哈希，**无任何 ID**。

## 5. 决定性否定：名字→匿名贴图在出货数据中零映射

用 64 位精确公式（比此前 variant_hunt 的 high32 版更强）对 24,261 张匿名贴图键测尽：

| 字符串源 | 规模 | 匿名贴图键命中 |
|---|---|---|
| ResourcePath.cfg 全路径 | 72,764 | **0** |
| 裸名/换扩展(18 种)/前缀(4 种)变体 | 11,851×23 | 0（.jpg 的 9 个 named 命中为噪声） |
| global.jstr 全串 | 297,278（贴图类 17,557） | 1（带空格的怪串，噪声级） |
| 目录路径哈希（5,653 目录×4 形态） | ~22k | 0 |
| 有名文件内嵌 u64 窗口（mtl/mdl/mesh/ani/ske/terrain 族/pu/tani） | 66,280 文件 | 0 |
| pcfg 链接键 | 8,480 | 贴图路径仅 11 |
| .pu/.tani 内嵌 u64 | 10,366 文件 | 0 |

池记录另证：24,226/24,261 匿名贴图键**在池里**（打包器认知它们），但池只存 ID 不存串。

## 6. 结论（对应任务三问）

1. **引擎怎么加载匿名贴图**：不存在可复原的「名字→匿名贴图」运行时映射。按名能加载的
   只有键=路径哈希的条目（有名 + 4,780 白捡）。匿名贴图的键 = 打包期源清单哈希，
   源字符串从未出货；按名加载失败后引擎只有 ".tga" 回退，再失败即加载失败。
2. **为什么名字和贴图编号断开**：打包器把 .tga 转成运行时贴图后**重新编址**——新键来自
   打包器私有源清单（pcfg 池里的包外 ID），该清单只出 ID 不出串。这不是损坏，是设计。
3. **~800 悬空名 + 24,260 匿名贴图怎么办**：静态字符串路线已数学性穷尽（上表），
   剩余通路只有内容特征（尺寸/codec/mips/哈希）+ UV 试贴 + 人工目检——
   **即四梯队②③④。IDA 阶段的目标（找运行时映射/加载函数）已达成：结论是"没有"**，
   从引擎侧证明了 Resolver 路线是唯一正确路线。

## 7. 对 Resolver 的直接投喂

1. `hash_hunt.py`/`resolver_probe.py` 升级为 64 位精确匹配（原先只有 high32）。
2. 归一化细节入 core：lowercase、`\`→`/`、**有符号 char**。
3. pcfg 池落盘为 sidecar：`cfg 路径 → ID → (∈pak / ∉pak)`；"∉pak 的 cfg 路径 ID" 集合
   = 四梯队需要配对的精确悬空清单（比 8,688 悬空名口径更完整）。
4. 链接表 8,480/9,636 条多对一别名 → sidecar 落盘（对 ani/材质等可能有零星收益）。
5. 匿名贴图「有名=UI 图标、匿名=世界/特效」两个人群零重叠的旧结论不变。

## 复现

```bash
python D:/TLGL/.scratch/ida_verify_dualhash.py   # 64 位公式 57,274 全量验证（见 §1）
python D:/TLGL/.scratch/pcfg_parse.py            # pcfg 状态机解析（本报告 §3 全部数字）
```

IDA 已命名函数（tlbbgl_x64.exe.i64 已保存）：`pak_dualhash_sdbm_in_HIGH/LOW`、
`FileSystem_GetFileID`、`FileSystem_OpenReadFile`、`FileSystem_ComposeFileHash_stem_infix_ext`、
`PackageManager_OpenReadFile`、`PackageManager_FindIndexEntry`、`FileLinkManager_Load_pcfg`、
`FileLinkMap_Insert`、`FileLinkManager_BuildFileLinkInfoMap`、`FileLinkFlatArray_Search`、
`FileSystem_Init`、`GameFileSystem_Mount(Wrap)`、`Compresser_Decompress`、
`Texture_LoadByName_tga_fallback`、`TexturePool_GetOrCreate`、`Texture_ExtractStem_Load_tga`、
`Lightmap_BuildNames_dds`、`ConvertCache_BuildName_rev_hash`。
