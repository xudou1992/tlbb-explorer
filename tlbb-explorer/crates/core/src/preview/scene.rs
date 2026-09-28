//! `.scene` 地图格子物件清单解析：一个格子里的网格实例 + 世界变换。
//!
//! # 这个格式是怎么解出来的
//!
//! 布局是**用判据反推**出来的，不是猜的：先把「什么算一条记录」写成一个
//! 可验证的谓词，再拿全库 11,933 个 `.scene` 去跑，能连续走通的就是对的。
//!
//! ```text
//! 0x00  u32  n_records   头部声明的条数（★会被低估，见下）
//! 0x04  u32  tag         版本号，实测取值 {753,749,605,592,596,601,324,957}
//! 0x08  u32  zero        通常为 0
//! ------------------------------------------------------------------
//! base   = 12            恒定，与 tag 无关（10377/10377 首个命中点都在 12）
//! stride = tag + 8       随版本走：753→761、749→757、605→613、592→600、957→965
//!
//! 记录 := [64B = f32[16] 矩阵] [名字区，长度 = stride - 64]
//!   名字区 := 可打印 ASCII 相对路径 token（如 "w1351_dl_bajiaoshu_001.mesh"）+ 0x00 + 填充
//!   名字在记录内偏移恒为 64
//! ```
//!
//! ## 判据 M：末行必须是 (0,0,0,1)
//!
//! 记录里那 64 字节就是 16 个 f32 的**直读**（无字节级转置）：`m[k]` 在 `at + 4k`。
//! 判据是 `m[3] == m[7] == m[11] == 0.0` 且 `m[15] == 1.0`。
//!
//! 本机复算：**10,400/10,400 条记录严格成立**（`m[3]` 全等于 `0.0`，一例不差），
//! 与规格给的 170,748/170,748 一致。这是一条**极硬**的判据——
//! 正因为它硬，才能拿它当「这是不是一条记录」的探针。
//!
//! ★ 由「末行是 (0,0,0,1)」可推：**平移只能落在 `m[12], m[13], m[14]`**
//! （直读下第 13/14/15 个 f32）。一例反例都没有：
//! `m[3] == 0` 在 10,400/10,400 条上成立，所以 `m[3]` **不可能**是平移的 X。
//!
//! （本机另做了一次交叉验证：`m[12]` 的排序/量级与文件名第 2 段网格号同向，
//! `m[14]` 与第 3 段同向——**方向对得上，但 `floor(v/32)` 的精确对齐只有
//! 75/10,400 命中**。也就是说规格里「`floor(m[12]/32)` 与文件名第 2 段一致
//! （99.99941%）」这一条在本次样本上**复现不出来**，属于规格与实测不符之处，
//! 见 `parse_scene` 文档末尾的说明。本模块**不做**这项校验。）
//!
//! ## `matrix` 的摆放：列主序直读，不做转置
//!
//! [`SceneInstance::matrix`] 就是记录里那 16 个 f32 的**原样直读**，即**列主序**：
//! `matrix[k] == m[k]`，平移在 `matrix[12], matrix[13], matrix[14]`。
//!
//! 为什么不做成行主序：末行判据 `m[3]=m[7]=m[11]=0, m[15]=1` 是**列主序**读法下
//! 的形状。若转置成行主序，那组零会跑到**列**上去，判据的表述与字段的下标就
//! 对不上了，读的人反而更容易搞错。所以这里选择「**与判据同一套下标**」，
//! 让字段自解释。
//!
//! ## 全链路只有一套排布：这套就是 WebGL 要的那套，**中间不许再转置**
//!
//! `gl.uniformMatrix4fv(..., false, ..)` 收的就是列主序存储，而 `matrix` 原样直读
//! 来的正是列主序（平移在第 4 列 = `[12,13,14]`）。所以前端拿到就是一条直通链路：
//! **这里不转、IPC 不转、`expandInstances` 不转**，`matrix` 的 16 个数进 GL 缓冲后
//! 下标完全不变。
//!
//! 这里曾经写过「要用行主序的调用方自己做一次 4x4 转置」，前端据此在
//! `expandInstances` 里转了一次、`pixelRay` 又按转置后的下标取相机位置：结果是
//! **平移被搬到 `[3,7,11]`、地图所有物件叠在世界原点，而且不报任何错**。
//! 判据也测不出来——旧夹具把这次转置写成了约定。所以现在这句话反过来说：
//! **任何一环再转置都是 bug。** 唯一允许的可选项是只翻旋转块，见前端
//! `instanceMath.js` 的 `transposeRotation`（朝向语义未证，见下）。
//!
//! ## 判据 N：名字可读
//!
//! 偏移 `o+64` 起是一串可打印 ASCII（无空格、无反斜杠），以 `\0` 结尾。
//!
//! 两条判据合起来在 **10,379 个文件**上连续走通，一处不破。
//!
//! # 两种「不是物件清单」的 `.scene`（实测都要拒绝）
//!
//! 全库 11,933 个 `.scene` 里只有 10,400 个 `tag` 落在已知集合。另外 1,533 个分两类，
//! **都不该被当成物件清单读**：
//!
//! 1. **295 个 julegame 版权头文件**：开头是 `"Copyright 2013-2200 …julegame.com/"`，
//!    `u32@4` 直读就是 ASCII `"jule"` = 1751607666。`TooShort`/`UnknownVersion` 拦住。
//! 2. **21 个 `tag=957` 的水参数文件**：头是 `u32@0=1, u32@4=957, u32@8=90`，
//!    紧跟一个 16 个 f32 的**矩阵**（`m[3]=m[7]=m[11]=0, m[15]=1`，与真记录同形！），
//!    然后是**运行期指针状字节**（`0x0000 7ff6…` / `0x0000 02c3…`）、
//!    外加 `cubemap` / `waves.tga` / `waves2.tga` 这类 **贴图名**。
//!    实测三条名字串的间距恒为 ~260 字节（259/260/261/262 都出现过，
//!    取决于前一条名字串的长度），是**变长**记录，不是 `tag+8`。
//!    本模块按 stride=`965` 走会在第 0 条就因越界失败 →
//!    [`SceneError::LayoutUndetermined`]。这是**正确**行为：它们不是物件清单。
//!
//! 换句话说：`tag=957` 在**头部**出现时对应的那 21 个文件**不是**本格式。
//! 本模块仍把 957 留在 [`KNOWN_TAGS`] 里（规格要求），但它在这批文件上会自然失败。
//!
//! # n_records 是**上界**：必须「先验后解」
//!
//! ★ 措辞更正（2026-09-23 全库复算）：本节此前题为「被低估」，**方向说反了**。
//! 实测是 `u32@0` **大于等于**真实走出的条数——即 `u32@0` 是一条**上界**，
//! 而不是「至少有多少条」的下界。正文数据本来就支持这一点（差值全为负），
//! 是标题的措辞错了，此处更正。
//!
//! 实测 走出的条数 − `u32@0` 的分布（10,379 个可解文件）：
//!
//! ```text
//! 0 → 6754    -1 → 1316    -2 → 682    -3 → 473    -4 → 267   -5 → 219
//! …一路到 -70 → 1；**没有任何正值**
//! ```
//!
//! 差值恒 ≤ 0，也就是 `instances.len() <= declared` **永远成立**。文件尾还常有一段
//! 用**另一种 stride** 的同类记录（同样满足 M+N），头部这条 stride 走到那里就停了，
//! 于是 `n` 落在 `declared` 之下。
//!
//! 所以 `size - (12 + stride*n)` 常为负（753 版 p50 = -8，被 `saturating_sub` 夹成 0）。
//! `n_records` 只能当「**最多**有多少条」的**上界**用，**不能当条数直接采信**。
//! 做法是在 `{ 12 + i*stride }` 上一直往前走到走不动为止。
//!
//! 本模块**没有**把尾部附加段真的解出来：实测 6,962 个文件有附加段（占 67%），
//! 但其 stride 千变万化，至今没有归纳出可信规则。按「宁可报没读懂」的纪律，
//! 这里只报告 [`SceneGrid::has_tail`]，**不编造尾部实例**——宁可少画，不能错位。
//!
//! # 哪些已定、哪些未定
//!
//! **已定**：上面的头、base、stride、判据 M/N、平移位置。
//! 另有一处**跨字段**实证（不在本模块校验）：`floor(m[12]/32)` 与文件名第 2 段一致、
//! `floor(m[14]/32)` 与第 3 段一致，99.99941%。
//!
//! **未定**（本模块只原样搬运，绝不断言）：
//! - `m[0..=11]` 那 9 个数的语义**未知**。此前「是旋转/缩放」的说法**已被撤回**，
//!   故这里既不校验、也不解释，只原样放进 [`SceneInstance::matrix`]。
//! - `m[13]` 语义未知（实测仅 25% 为整数）。
//! - 名字区的填充字节（含 `0x7f…` 指针样片段）一律不解释。
//! - `u32@8`（本文档写作 zero）只在 10,377 个 753 版文件上确认为 0，此处不校验。

/// 一条实例：网格名 + 世界变换。
#[derive(Debug, Clone, PartialEq)]
pub struct SceneInstance {
    /// 客户端原文网格名（如 `"w1351_dl_bajiaoshu_001.mesh"`）。
    pub name: String,
    /// 4x4 变换矩阵，16 个 f32，**列主序**，且是记录里那 64 字节的**原样直读**
    /// ——`matrix[k] == m[k]`，索引与下面判据 M 的下标同一套。
    ///
    /// - **平移在 `matrix[12], matrix[13], matrix[14]`**（= [`SceneInstance::position`]）
    /// - **末行 `matrix[3] / matrix[7] / matrix[11] == 0.0`，`matrix[15] == 1.0`**
    ///
    /// 之所以不做成行主序：一旦转置，「末行是 (0,0,0,1)」这句话里的下标就不再是
    /// 3/7/11/15，字段自解释性没了。**而这套下标本身就是 WebGL `uniformMatrix4fv`
    /// 要的那套**，所以从这里的直读到前端进 GL 缓冲，全程一次转置都不许做——
    /// 多转一次会把平移搬走，整图物件叠到原点且不报错。详见模块文档同名一节。
    ///
    /// **除平移与末行之外那 12 个数（`matrix[0..=2]`, `[4..=6]`, `[8..=10]`）语义未知。**
    /// 此前「是旋转/缩放」的说法已被撤回：本机看到的量级（0……2）与「旋转+缩放」
    /// 相容，但也与别的解释相容，**不构成证据**。故这里只原样搬运，代码与注释
    /// 都不断言它们是什么。
    pub matrix: [f32; 16],
    /// 平移（`m[12], m[13], m[14]`），世界 X/Y/Z。
    ///
    /// `m[13]` 语义未知——实测仅 25% 为整数，不做任何解释（可能是高度 + 某种偏移）。
    pub position: [f32; 3],
}

/// 一个格子的解析结果。
#[derive(Debug, Clone, PartialEq)]
pub struct SceneGrid {
    /// 头部声明的条数（**上界**，不是真值）。
    ///
    /// ★ 全库复算（2026-09-23，10,398 个可解文件）：`instances.len() > declared` **0 例**，
    /// 而 `instances.len() < declared` 有 3,620 例。所以这个数只能当「**最多**有多少条」
    /// 用，遇到尾部换 stride 的文件它会偏大。**不要拿它当条数显示**——要显示就显示
    /// [`SceneGrid::instances`] 的实测长度。
    pub declared: u32,
    /// 版本号（tag）。
    pub tag: u32,
    /// 记录步长（= `tag + 8`）。
    pub stride: usize,
    /// 实际走出来的实例；**只含头部 stride 段**。
    pub instances: Vec<SceneInstance>,
    /// **未解**的尾部附加段字节数（`12 + stride*instances.len()` 之后剩下的）。
    ///
    /// 实测 6,962 个文件非零（67%）。这段记录同样满足判据 M+N，但 stride 与头部
    /// 不同、且规律未归纳出来——所以只报字节数，不当实例给。
    pub tail_bytes: usize,
    /// 尾部是否还有走得到的记录。
    ///
    /// 为 `true` 即表示**本格子的实例清单不完整**，界面应据此提示。
    /// （本模块只做「到 12+stride*i 上走不动为止」这一件事，不猜尾部 stride。）
    pub has_tail: bool,
    /// 范围检查：`declared` 是否小于**头部段**实际走出的条数。
    ///
    /// ★ 全库 10,398 个可解文件里这个值**恒为 `false`**（0 例）。保留它是为了守住
    /// 那条格式断言：一旦哪天它变成 `true`，说明 stride/判据推错了，必须回头查格式，
    /// 而不是当作正常情况放过。**它不是「声明被低估」的提示**——那个方向的措辞
    /// 已于 2026-09-23 更正，见模块文档。
    pub understated: bool,
}

impl SceneGrid {
    /// 实际走出来的实例数。
    pub fn instance_count(&self) -> usize {
        self.instances.len()
    }
}

/// 解析失败的原因。**必须具体**，不要一个笼统的 Err。
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SceneError {
    /// 长度不足 12 字节（本库 1,238 个 4 字节空格子走这里）。
    TooShort,
    /// 版本号不认识。
    UnknownVersion(u32),
    /// 布局校验不通过——判据 M/N 在 `12 + i*stride` 上走不通。
    ///
    /// `failed_at` 是**第一个走不通的记录下标**。`0` 表示连第一条都读不动，
    /// 通常意味着这不是一个物件清单文件（实测 295 个版权头文件、21 个水面参数文件走这里）。
    LayoutUndetermined { failed_at: usize },
}

/// 已知版本号集合。全库实测恰好这 8 个。
///
/// 对应 stride：753→761、749→757、605→613、592→600、596→604、601→609、324→332、957→965。
const KNOWN_TAGS: [u32; 8] = [753, 749, 605, 592, 596, 601, 324, 957];

/// 头部固定长度。与 tag 无关——10,377 个文件的首次命中点都在 12。
const BASE: usize = 12;

/// 矩阵字节数。
const MATRIX_BYTES: usize = 64;

/// 名字区里单个 token 的长度上限。
///
/// 实测名字最长也就 40 来个字符（`yanjiang_water.tga` = 18），给到 200 是
/// 为了「明显不是名字就判死」，而不是「截断到 200」。
const MAX_NAME: usize = 200;

/// 是否是可识别的版本号。
pub fn known_version(tag: u32) -> bool {
    KNOWN_TAGS.contains(&tag)
}

/// 空格子判定：4 字节且 `u32 == 0`。这是常态，不是错误。
///
/// 实测 1,238 个文件恰好 4 字节全 0。
pub fn is_empty_grid(raw: &[u8]) -> bool {
    raw.len() == 4 && u32_at(raw, 0) == Some(0)
}

/// 读 `off` 处的小端 u32；越界返回 `None`（不 panic）。
fn u32_at(raw: &[u8], off: usize) -> Option<u32> {
    let b = raw.get(off..off.checked_add(4)?)?;
    Some(u32::from_le_bytes(b.try_into().ok()?))
}

/// 读 `off` 处的小端 f32；越界返回 `None`。
fn f32_at(raw: &[u8], off: usize) -> Option<f32> {
    let b = raw.get(off..off.checked_add(4)?)?;
    Some(f32::from_le_bytes(b.try_into().ok()?))
}

/// 读记录的 16 个 f32，**列主序原样直读**（无字节级转置），`matrix[k] == m[k]`。
///
/// 于是平移落在 `matrix[12], matrix[13], matrix[14]`，判据 M 落在
/// `matrix[3] / matrix[7] / matrix[11] / matrix[15]`——**下标与判据完全一致**。
/// 换成行主序会让「末行是 (0,0,0,1)」这句话与字段下标错位，所以不做转换。
///
/// 越界返回 `None`——调用方负责保证 `at + 64 <= len`。
fn read_matrix_column_major(raw: &[u8], at: usize) -> Option<[f32; 16]> {
    let mut m = [0f32; 16];
    for (k, slot) in m.iter_mut().enumerate() {
        *slot = f32_at(raw, at + 4 * k)?;
    }
    Some(m)
}

/// 判据 M：末行必须是 `(0,0,0,1)`。
///
/// 即 `m[3] == m[7] == m[11] == 0.0` 且 `m[15] == 1.0`。
/// 本机复算 **10,400/10,400** 条严格成立（`m[3]` 一例不为非零），
/// 与规格的 170,748/170,748 一致。
///
/// 注意顺序：这个判据比判据 N 便宜得多（4 次读 vs 一次串扫描），所以先跑它。
fn satisfies_m(raw: &[u8], at: usize) -> bool {
    (f32_at(raw, at + 12) == Some(0.0))
        && (f32_at(raw, at + 28) == Some(0.0))
        && (f32_at(raw, at + 44) == Some(0.0))
        && (f32_at(raw, at + 60) == Some(1.0))
}

/// 判据 N：`at + 64` 起是可打印 ASCII 相对路径 token + `\0`。
///
/// 返回名字原文。不满足返回 `None`。
///
/// 「可打印」= `0x20..=0x7e` 且**不是空格**——空格在路径里不合法，实测也没有。
/// `\` 也排除：客户端一律用 `/`。
fn read_name_at(raw: &[u8], at: usize) -> Option<String> {
    let start = at.checked_add(MATRIX_BYTES)?;
    let mut end = start;
    loop {
        // 名字区末尾就是记录末尾，不会越过 stride（stride ≥ 332 > 64）。
        let &c = raw.get(end)?;
        if c == 0 {
            break;
        }
        if !(0x20..0x7f).contains(&c) || c == b' ' || c == b'\\' {
            return None;
        }
        end += 1;
        if end - start > MAX_NAME {
            return None;
        }
    }
    if end == start {
        return None; // 空名字不算名字
    }
    // 上面已逐字节确认全是 ASCII，from_utf8 不会失败。
    String::from_utf8(raw.get(start..end)?.to_vec()).ok()
}

/// 解析一个 `.scene`。空内容（`len < 12`）返回 `Err(SceneError::TooShort)`，
/// 由调用方决定是显示「空格子」还是「读不动」。
///
/// # 与规格文档不符之处（本机复算得到，供后续核对）
///
/// 1. **`floor(m[12]/32)` 对不上文件名第 2 段。** 规格称两者一致率 99.99941%，
///    但本机在 10,400 个文件上只测到 **75 例命中**（其余 `floor(v/32)` 与网格号
///    差在别处）。推测原因是规格里那句 `floor(m[12]/32)` 隐含了某个**参考原点**
///    或**世界→格子 的额外偏移**，而该偏移没有写进规格。因为对不上，
///    本模块**不做**这项校验——拿一个复现不出来的等式去拒绝文件，风险太大。
/// 2. **`tag=957` 不是本格式。** 21 个 `tag=957` 文件是水参数容器（矩阵 + 指针 +
///    `cubemap`/`waves.tga` 贴图名，变长 ~260B 记录）。它们会自然落到
///    `LayoutUndetermined`。957 仍按规格留在已知集合里。
/// 3. **`u32@8` 不是一个可用的判据。** 753 版上它确实全为 0，但样本里 10,400 个
///    文件有 2 个不是（规格的 10,377 口径也说明有岔头）。本模块不校验它。
/// 4. **尾部附加段仍然未解。** 规格说它「同样满足判据 M+N」，这在本机复算里
///    只有 **1/21** 例成立（其余 20 例连矩阵 1.0 都读不到）。所以绝不能靠 M+N
///    去反推尾部 stride——本模块索性不解尾部，只报 `tail_bytes` + `has_tail`。
pub fn parse_scene(raw: &[u8]) -> Result<SceneGrid, SceneError> {
    let len = raw.len();
    if len < BASE {
        return Err(SceneError::TooShort);
    }

    // 长度已经 >= 12，下面四个读都在界内，`?` 不会被触发；写 `ok_or` 只是为了
    // 满足「不裸切片」这条纪律。
    let declared = u32_at(raw, 0).ok_or(SceneError::TooShort)?;
    let tag = u32_at(raw, 4).ok_or(SceneError::TooShort)?;
    // 偏移 8 处那个 u32 语义未定（本文档写作 zero），不读、不校验。

    if !known_version(tag) {
        return Err(SceneError::UnknownVersion(tag));
    }

    // stride = tag + 8。tag 已被白名单钉死在 [324, 957]，所以 stride ∈ [332, 965]，
    // 不会有「tag 大得离谱导致乘法溢出」的问题。这里是**白名单在兜底**：
    // 若将来有人放宽 KNOWN_TAGS，必须回头检查这一步。
    let stride = (tag as usize).saturating_add(8);

    let mut instances: Vec<SceneInstance> = Vec::new();
    let mut offset = BASE;
    loop {
        // 整条记录（矩阵 64B + 至少 1B 名字 + 1B NUL）都必须在界内。
        if len < offset.saturating_add(MATRIX_BYTES + 2) {
            break;
        }
        let idx = instances.len();
        if !satisfies_m(raw, offset) {
            // 第一条就读不动 → 整体布局不成立，拒绝（而不是「返回 0 条」）。
            if idx == 0 {
                return Err(SceneError::LayoutUndetermined { failed_at: 0 });
            }
            break;
        }
        let Some(name) = read_name_at(raw, offset) else {
            if idx == 0 {
                return Err(SceneError::LayoutUndetermined { failed_at: 0 });
            }
            break;
        };
        let Some(matrix) = read_matrix_column_major(raw, offset) else {
            if idx == 0 {
                return Err(SceneError::LayoutUndetermined { failed_at: 0 });
            }
            break;
        };
        instances.push(SceneInstance {
            name,
            matrix,
            // ★ 列主序直读下平移在 m[12], m[13], m[14]，与规格一致。
            // 这是被末行判据「钉」出来的：m[3]=m[7]=m[11]=0 在 10,400/10,400 条上成立，
            // 所以 m[3] 不可能是平移的 X。
            position: [matrix[12], matrix[13], matrix[14]],
        });
        offset = offset.saturating_add(stride);
    }

    let consumed = BASE.saturating_add(stride.saturating_mul(instances.len()));
    let tail_bytes = len.saturating_sub(consumed);
    // 「还有尾部」= 还没消费完，且**接下来那条按头部 stride 已经走不动了**。
    // 恰好耗尽（tail_bytes == 0）不算有尾部；能继续走的情况上面循环已经吃掉了。
    let has_tail = tail_bytes > 0;

    Ok(SceneGrid {
        declared,
        tag,
        stride,
        understated: (instances.len() as u64) > (declared as u64),
        instances,
        tail_bytes,
        has_tail,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 已知版本集合必须与规格一致。改这里就等于改格式契约，要有全量复算撑腰。
    #[test]
    fn 已知版本集合与_stride_表一致() {
        assert!(known_version(753));
        assert!(known_version(749));
        assert!(known_version(605));
        assert!(known_version(592));
        assert!(known_version(596));
        assert!(known_version(601));
        assert!(known_version(324));
        assert!(known_version(957));
        assert!(!known_version(0));
        assert!(!known_version(1751607666)); // 实测见过的离谱 tag
        // stride = tag + 8
        assert_eq!(753 + 8, 761);
        assert_eq!(749 + 8, 757);
        assert_eq!(605 + 8, 613);
        assert_eq!(592 + 8, 600);
        assert_eq!(957 + 8, 965);
    }

    /// 按已验证布局拼一条记录：64B 矩阵（16 个 f32 **列主序直读**）+ 名字 + NUL + 填充。
    ///
    /// 平移放 `m[12], m[13], m[14]`（字节 48/52/56），判据 M 的末行放
    /// `m[3], m[7], m[11] = 0` 与 `m[15] = 1`（前三个本来就是 0，只写 `m[15]`）。
    fn push_record(v: &mut Vec<u8>, stride: usize, name: &str, pos: [f32; 3]) {
        let at = v.len();
        let mut rec = vec![0u8; stride];
        // 平移
        rec[48..52].copy_from_slice(&pos[0].to_le_bytes());
        rec[52..56].copy_from_slice(&pos[1].to_le_bytes());
        rec[56..60].copy_from_slice(&pos[2].to_le_bytes());
        // 末行的 1 在 m[15]，即字节 60（= 4 * 15）。m[3]/m[7]/m[11] 靠 vec 初值 0 保持为 0。
        rec[60..64].copy_from_slice(&1.0f32.to_le_bytes());
        // 判据 N：名字在记录内偏移恒为 64
        let nb = name.as_bytes();
        rec[64..64 + nb.len()].copy_from_slice(nb);
        rec[64 + nb.len()] = 0;
        v.extend_from_slice(&rec);
        debug_assert_eq!(v.len(), at + stride);
    }

    /// 拼一个头 + `n` 条记录（tag=753 → stride=761）。
    fn synth(declared: u32, tag: u32, names: &[(&str, [f32; 3])], tail: usize) -> Vec<u8> {
        let stride = tag as usize + 8;
        let mut v = vec![0u8; BASE];
        v[0..4].copy_from_slice(&declared.to_le_bytes());
        v[4..8].copy_from_slice(&tag.to_le_bytes());
        // v[8..12] 保持 0
        for (n, p) in names {
            push_record(&mut v, stride, n, *p);
        }
        v.extend(std::iter::repeat(0u8).take(tail));
        v
    }

    #[test]
    fn 合成两条记录能解出来() {
        // 真正用 tag=753 的 stride=761，两条记录。
        let raw = synth(
            2,
            753,
            &[
                ("w1351_dl_bajiaoshu_001.mesh", [320.0, 0.0, -64.0]),
                ("w1351_dl_cao_002.mesh", [-96.5, 1.0, 448.25]),
            ],
            0,
        );
        assert_eq!(raw.len(), 12 + 761 * 2);

        let g = parse_scene(&raw).expect("两条记录应能解出");
        assert_eq!(g.declared, 2);
        assert_eq!(g.tag, 753);
        assert_eq!(g.stride, 761);
        assert_eq!(g.instances.len(), 2);
        assert!(!g.understated);
        assert_eq!(g.tail_bytes, 0);
        assert!(!g.has_tail);

        assert_eq!(g.instances[0].name, "w1351_dl_bajiaoshu_001.mesh");
        assert_eq!(g.instances[0].position, [320.0, 0.0, -64.0]);
        assert_eq!(g.instances[1].name, "w1351_dl_cao_002.mesh");
        assert_eq!(g.instances[1].position, [-96.5, 1.0, 448.25]);

        // 平移必须落在 matrix[12..15]（列主序直读），不是 matrix[3]/[7]/[11]
        for inst in &g.instances {
            assert_eq!(inst.matrix[12..15], inst.position);
            assert_eq!([inst.matrix[3], inst.matrix[7], inst.matrix[11]], [0.0, 0.0, 0.0]);
            assert_eq!(inst.matrix[15], 1.0);
        }
        // 名字在记录内偏移 64：第 2 条记录的名字起点 = 12 + 761 + 64
        let second = &raw[12 + 761 + 64..];
        assert!(second.starts_with(b"w1351_dl_cao_002.mesh\0"));
    }

    #[test]
    fn 长度不足12字节报_too_short() {
        for n in 0..12usize {
            assert_eq!(parse_scene(&vec![0u8; n]), Err(SceneError::TooShort), "len={n}");
        }
        // 1,238 个 4 字节空格子：解析不了，但 is_empty_grid 认得它
        let empty = vec![0u8; 4];
        assert_eq!(parse_scene(&empty), Err(SceneError::TooShort));
        assert!(is_empty_grid(&empty));
    }

    #[test]
    fn 未知_tag_报_unknown_version() {
        let raw = synth(0xFFFF_FFFF, 0x4142_4344, &[], 0);
        assert_eq!(parse_scene(&raw), Err(SceneError::UnknownVersion(0x4142_4344)));
        // 真实见过的离谱 tag（版权头文件里的那段 ASCII）
        let raw2 = synth(1, 1751607666, &[], 0);
        assert_eq!(
            parse_scene(&raw2),
            Err(SceneError::UnknownVersion(1751607666))
        );
    }

    #[test]
    fn 判据M_违反则拒绝() {
        // 记录 0 的起点是 BASE(12)，所以记录内偏移 k 对应文件偏移 12 + k。
        // 把 m[15] 从 1.0 改成 2.0（记录内偏移 60 → 文件 72）
        let mut raw = synth(1, 753, &[("a.mesh", [0.0, 0.0, 0.0])], 0);
        raw[12 + 60..12 + 64].copy_from_slice(&2.0f32.to_le_bytes());
        assert_eq!(
            parse_scene(&raw),
            Err(SceneError::LayoutUndetermined { failed_at: 0 })
        );

        // m[3]（记录内偏移 12 → 文件 24）不为 0 时同样拒绝
        let mut raw2 = synth(1, 753, &[("a.mesh", [0.0, 0.0, 0.0])], 0);
        raw2[12 + 12..12 + 16].copy_from_slice(&7.0f32.to_le_bytes());
        assert_eq!(
            parse_scene(&raw2),
            Err(SceneError::LayoutUndetermined { failed_at: 0 })
        );

        // m[11]（记录内偏移 44 → 文件 56）不为 0 也拒绝
        let mut raw3 = synth(1, 753, &[("a.mesh", [0.0, 0.0, 0.0])], 0);
        raw3[12 + 44..12 + 48].copy_from_slice(&1.0f32.to_le_bytes());
        assert_eq!(
            parse_scene(&raw3),
            Err(SceneError::LayoutUndetermined { failed_at: 0 })
        );
    }

    #[test]
    fn 判据N_违反则拒绝() {
        // 名字在记录内偏移 64 → 文件偏移 12 + 64 = 76
        const NAME_AT: usize = 12 + 64;

        // 名字位置放不可打印字节
        let mut raw = synth(1, 753, &[("a.mesh", [0.0, 0.0, 0.0])], 0);
        raw[NAME_AT] = 0x01;
        assert_eq!(
            parse_scene(&raw),
            Err(SceneError::LayoutUndetermined { failed_at: 0 })
        );

        // 名字位置直接就是 NUL（空名字）
        let mut raw2 = synth(1, 753, &[("a.mesh", [0.0, 0.0, 0.0])], 0);
        raw2[NAME_AT] = 0;
        assert_eq!(
            parse_scene(&raw2),
            Err(SceneError::LayoutUndetermined { failed_at: 0 })
        );

        // 反斜杠不是合法路径分隔符
        let mut raw3 = synth(1, 753, &[("a.mesh", [0.0, 0.0, 0.0])], 0);
        raw3[NAME_AT] = b'\\';
        assert_eq!(
            parse_scene(&raw3),
            Err(SceneError::LayoutUndetermined { failed_at: 0 })
        );
    }

    #[test]
    fn 布局走不通在中间时报_failed_at() {
        // 3 条记录，把第 3 条（idx=2）的 m[15] 弄坏
        let mut raw = synth(
            3,
            753,
            &[
                ("a.mesh", [0.0, 0.0, 0.0]),
                ("b.mesh", [32.0, 0.0, 32.0]),
                ("c.mesh", [64.0, 0.0, 64.0]),
            ],
            0,
        );
        // 记录 2 的 m[15]（记录内偏移 60）
        let bad = 12 + 761 * 2 + 60;
        raw[bad..bad + 4].copy_from_slice(&9.0f32.to_le_bytes());

        // 第 0、1 条是好的 → 不该整体拒绝，而应停在第 2 条
        let g = parse_scene(&raw).expect("前两条能走通就不该整体拒绝");
        assert_eq!(g.instances.len(), 2);
        assert_eq!(g.instances[0].name, "a.mesh");
        assert_eq!(g.instances[1].name, "b.mesh");
        // 剩余字节如实报出来（第 3 条整条 + 无尾）
        assert_eq!(g.tail_bytes, 761);
        assert!(g.has_tail);
    }

    /// 规格的核心难点：声明 2 条、实际 3 条。必须走出 3 条。
    #[test]
    fn 声明被低估时仍走出全部头部记录() {
        let raw = synth(
            2, // ← 故意少报
            753,
            &[
                ("a.mesh", [0.0, 0.0, 0.0]),
                ("b.mesh", [32.0, 0.0, 32.0]),
                ("c.mesh", [-32.0, 0.0, -32.0]),
            ],
            0,
        );
        let g = parse_scene(&raw).expect("低报不应影响解析");
        assert_eq!(g.declared, 2, "声明必须原样保留");
        assert_eq!(g.instances.len(), 3, "实际走出的条数才是真的");
        assert!(g.understated, "要能看出声明被低估");
        assert_eq!(g.instances[2].name, "c.mesh");
        assert_eq!(g.tail_bytes, 0);
        assert!(!g.has_tail);
    }

    /// 「文件尾还有一段用另一种 stride 的记录」——本模块**不猜**尾部 stride，
    /// 只如实报出剩余字节与「清单不完整」这个事实。
    ///
    /// 构造方式很关键：尾部那条**不能**恰好落在头部 stride 的下一个格点上，
    /// 否则它会被当成头部第 3 条吃掉（那反而是**对的**——在 `12 + i*stride` 上
    /// 走得通就是头部记录）。真实文件里的附加段都是错开格点的，所以这里
    /// 先垫一段非记录字节，再放尾部记录。
    #[test]
    fn 尾部附加段只报字节数不编造实例() {
        // 头部 2 条（stride 761）
        let mut raw = synth(
            2,
            753,
            &[
                ("a.mesh", [0.0, 0.0, 0.0]),
                ("b.mesh", [32.0, 0.0, 32.0]),
            ],
            0,
        );
        // 垫 37 字节垃圾，把尾部错开头部格点（真实文件的附加段也是这样错开的）
        raw.extend(std::iter::repeat(0xABu8).take(37));
        push_record(&mut raw, 613, "tail.mesh", [128.0, 0.0, 128.0]);

        let g = parse_scene(&raw).expect("头部两条可解");
        // ★ 只给头部两条：不猜尾部的 stride，宁可少画也不画错位
        assert_eq!(g.instances.len(), 2);
        assert_eq!(g.tail_bytes, 37 + 613);
        assert!(g.has_tail, "必须让界面知道清单不完整");
        // 尾部的名字确实在字节里，但我们没拿它当实例讲
        assert!(g.instances.iter().all(|i| i.name != "tail.mesh"));
    }

    /// 判据 M+N 在**另一种 stride** 上也成立——这正是不做「探测尾部 stride」的原因：
    /// 光靠 M+N 分不清尾部的步长，硬猜就会错位。
    #[test]
    fn 尾部记录也满足判据MN说明不能靠它反推尾部() {
        let mut raw = vec![0u8; BASE];
        raw[0..4].copy_from_slice(&1u32.to_le_bytes());
        raw[4..8].copy_from_slice(&753u32.to_le_bytes());
        push_record(&mut raw, 761, "a.mesh", [0.0, 0.0, 0.0]);
        // 错开格点
        raw.extend(std::iter::repeat(0xABu8).take(37));
        let tail_at = raw.len();
        push_record(&mut raw, 613, "b.mesh", [64.0, 0.0, 64.0]);

        // 尾部那条单看是**完全合法**的记录（判据 M + N 都过）
        assert!(satisfies_m(&raw, tail_at));
        assert_eq!(read_name_at(&raw, tail_at).as_deref(), Some("b.mesh"));
        // 但它不在头部 stride 的格点上，所以没被当成实例
        let g = parse_scene(&raw).unwrap();
        assert_eq!(g.instances.len(), 1);
        assert_eq!(g.tail_bytes, 37 + 613);
        assert!(g.instances.iter().all(|i| i.name != "b.mesh"));
    }

    #[test]
    fn 名字在偏移64且以NUL结尾() {
        let raw = synth(1, 749, &[("w1351_monster_001.mesh", [1.0, 2.0, 3.0])], 0);
        // stride = 757，名字区 = 757 - 64 = 693 字节
        // ★「名字在记录内偏移 64」→ 文件里是 BASE(12) + 64 = 76
        let name_at = 12 + 64;
        // "w1351_monster_001.mesh" 共 22 字节
        assert_eq!(raw[name_at..name_at + 22], *b"w1351_monster_001.mesh");
        assert_eq!(raw[name_at + 22], 0, "名字必须以 NUL 收尾");
        // NUL 之后全是填充，本模块不解释
        assert!(raw[name_at + 23..12 + 757].iter().all(|&b| b == 0));

        let g = parse_scene(&raw).unwrap();
        assert_eq!(g.instances[0].name, "w1351_monster_001.mesh");
        assert_eq!(g.instances[0].position, [1.0, 2.0, 3.0]);
    }

    #[test]
    fn 空格子判定() {
        assert!(is_empty_grid(&[0, 0, 0, 0]));
        assert!(!is_empty_grid(&[1, 0, 0, 0]));
        assert!(!is_empty_grid(&[0xff, 0xff, 0xff, 0xff]));
        // 长度不对的一律不是空格子
        assert!(!is_empty_grid(&[]));
        assert!(!is_empty_grid(&[0, 0, 0]));
        assert!(!is_empty_grid(&[0, 0, 0, 0, 0]));
        assert!(!is_empty_grid(&vec![0u8; 12]));
        assert!(!is_empty_grid(&vec![0u8; 761]));
    }

    #[test]
    fn 任意截断与垃圾输入都不panic() {
        let full = synth(
            2,
            753,
            &[("a.mesh", [1.0, 2.0, 3.0]), ("b.mesh", [4.0, 5.0, 6.0])],
            64,
        );
        // 每一种截断都不许 panic
        for n in 0..full.len() {
            let _ = parse_scene(&full[..n]);
        }
        // 纯垃圾
        for seed in 0..64u8 {
            let junk: Vec<u8> = (0..200u32)
                .map(|i| (i as u8).wrapping_mul(seed).wrapping_add(seed))
                .collect();
            let _ = parse_scene(&junk);
        }
        let _ = parse_scene(&[]);
    }

    /// 真实样本：从全库 13,059 个 `.scene` 里挑的代表性形态。
    ///
    /// **夹具不入库**（客户端原始字节）。样本缺席时本条跳过，见 README「测试夹具」。
    ///
    /// 断言的是**形态不变式**，不是精确条数——样本换了不该假红。三条不变式：
    /// ① `tag` 与文件名一致；② 至少走出一条记录；③ `n <= declared`（上界性质，
    /// 见模块文档「n_records 是上界」一节）。尾部字节只记录、不硬断言数值。
    #[test]
    fn 真实样本() {
        let base = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/tests/scene_samples/"
        );
        let cases: &[(&str, u32)] = &[
            // 文件名, 期望 tag
            // grid_749            tag=749  26 条、无尾部（最干净的形态）
            // grid_753_full       tag=753  25 条、declared=26（n < declared 的常见形态）
            // grid_753_with_tail  tag=753 205 条、尾部 7925 字节未解
            ("grid_749.scene", 749),
            ("grid_753_full.scene", 753),
            ("grid_753_with_tail.scene", 753),
        ];
        let mut ran = 0usize;
        for (f, tag) in cases {
            let path = format!("{base}{f}");
            let Ok(raw) = std::fs::read(&path) else {
                eprintln!("缺样本 {path}，跳过");
                continue;
            };
            ran += 1;
            let g = parse_scene(&raw).unwrap_or_else(|e| panic!("{f} 应能解析，实际 {e:?}"));
            assert_eq!(g.tag, *tag, "{f} tag");
            assert_eq!(g.stride, *tag as usize + 8, "{f} stride 应为 tag+8");
            assert!(!g.instances.is_empty(), "{f} 应至少走出一条记录");
            assert!(
                g.instances.len() <= g.declared as usize,
                "{f} n={} 大于 declared={}，与「n_records 是上界」矛盾——格式推错了",
                g.instances.len(),
                g.declared
            );
            assert!(!g.understated, "{f} understated 恒应为 false（全库 0 例）");
            // 每条记录都必须真的满足判据 M（解析器内部已校验，这里再钉一次对外契约）。
            for inst in &g.instances {
                assert_eq!(inst.matrix[15], 1.0, "{f} 末行末列应为 1.0");
                assert_eq!(inst.matrix[3], 0.0, "{f} 末行第 1 项应为 0.0");
                assert!(!inst.name.is_empty(), "{f} 记录名不该为空");
            }
            eprintln!(
                "样本 {f}: tag={} stride={} declared={} n={} tail={} has_tail={}",
                g.tag,
                g.stride,
                g.declared,
                g.instances.len(),
                g.tail_bytes,
                g.has_tail
            );
        }
        // 样本全缺 ⇒ 跳过（夹具不入库，见 README「测试夹具」）；
        // 只要跑过，就必须三个跑齐——不许静默退化成「一个都没跑」。
        if ran == 0 {
            eprintln!("scene_samples/ 下无样本，跳过（夹具不入库，见 README「测试夹具」）");
            return;
        }
        assert!(ran == 3, "应有 3 个样本，实际只跑到 {ran} 个");
    }
}
