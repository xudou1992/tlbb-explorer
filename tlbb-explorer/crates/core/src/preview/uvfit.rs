//! uvfit 核心：匿名贴图池评分管线（从 `bin/uvfit.rs` 抽出的 lib 部分，
//! 单 mesh 版 `bin/uvfit.rs` 与批量版 `bin/uvfit_batch.rs` 共用同一实现）。
//!
//! 评分思路（**口径冻结**——任何一步改了都会破坏与 3 个生产候选缓存的
//! 逐位对拍，见 [`tests::replay_production_candidate_caches`]）：
//!
//! 1. 匿名贴图池：`type='texture' AND path IS NULL AND w,h≥512 AND
//!    codec IN('RGBA32','BC3') AND mips≥4`。这是**特征先验**（角色贴图的
//!    尺寸/编码习惯），只是筛选器，不是证据；证据在指标里。
//! 2. 每张贴图盒式降采样到 [`GRID`]² 亮度。
//! 3. mesh 的 UV 三角形栅格化成 256² 的岛内 mask。
//! 4. 岛内/岛外亮度方差比 `inside/(outside+4)`：真被画过的贴图，岛内是
//!    绘画细节（高方差）、岛外是溢色垫底（低方差）；错贴图的岛外多半
//!    还是别人的绘画内容。
//!
//! v0.4.1 起每候选在旧 score 之外追加因子面板 [`Factors`] 与聚合分
//! `adjustedScore`（黑底/白底托底修正是核心），见文件中部 v0.4.1 一节的
//! 说明；旧 score 的计算与展示逐位不动，单跑版 --emit-cache 仍输出旧格式。
//!
//! 得分是特征指标，不是归属结论——归属只有人工确认（🟢）才算数。
//! adjustedScore/gradedV2 同样只是「系统评分」，不是「正确率」。
//!
//! 批量版存在的理由：单 mesh 版每跑一次都重新解码整池 1,650 张（实测
//! ~10s，大头在池解码）。[`decode_pool`] 把解码 + 降采样结果留在内存里
//! 一次复用，之后每个 mesh 只剩栅格化 + 方差评分（毫秒级）。注意池缓存
//! 的**主通道是亮度**而不是 RGBA：bin 版的 [`downsample`] 是从原 RGBA 一步
//! 算到 256² 亮度（逐像素加权后平均），中途没有 RGBA 中间态；「先降采样
//! RGBA 再算亮度」在数学上不等价，会破坏对拍，所以内存形态以亮度为准。
//! v0.4.1 追加的 alpha/颜色证据通道（[`PoolTex::alpha`]/[`PoolTex::color`]
//! ）是独立的降采样结果，与亮度通道互不相干。

use std::collections::HashMap;
use std::path::Path;

use rusqlite::Connection;

use crate::jpak::{Pak, Record};
use crate::payload;

/// UV 栅格与降采样的统一口径。bin 版的冻结常量，批量版沿用同一尺寸。
pub const GRID: usize = 256;

// ─────────────────────────────────────────────────────────────────────────────
// v0.4.1 拆因子评分（新增，不改旧 score）
//
// 背景：旧口径 `score = insideVar/(outsideVar+4)` 在「亮内容稀疏摊在近纯黑
// 底上」时岛外方差≈0，分母只剩 +4 的平滑项，分数爆炸（实测 topScore 高达
// 3903 的值进了 high 档）。v0.4.1 把每候选输出拆成因子面板 [`Factors`]，并
// 给出聚合的 `adjustedScore`；**旧 score/insideVar/outsideVar 的计算与展示
// 逐位不动**（对拍契约），单跑版 --emit-cache 仍用旧格式。
//
// 措辞原则（数据侧落地）：这里的分数永远是「系统评分」，不是「正确率」——
// adjustedScore/gradedV2 只回答「系统有多大把握」，归属结论只有人工确认。
// ─────────────────────────────────────────────────────────────────────────────

/// v0.4.1 全部可调常量集中在此。旧 score 的计算不经过这里（对拍冻结）；
/// 这里的每个值只影响 factors/adjustedScore。常量依据见各字段注释。
pub struct FactorParams {
    /// uvFit 饱和曲线尺度 k：`uvFit = 1 - 1/(1 + ratio/k)`。
    /// k=8 时 ratio=8 → 0.5、旧 high 线 6.0 → 0.43、mid 线 3.0 → 0.27：
    /// 饱和拐点落在 high 线略上方，0..1 区间里给 mid/high 段保留了可分辨
    /// 的梯度；ratio→∞ 时渐近 1（方差比没有上界，必须饱和才能当「因子」用）。
    pub uv_sat_scale: f64,
    /// 岛外方差的最低托底（用户规格示例值）。黑底/白底判定成立时
    /// adjustedScore 的分母托到 `max(本值, 整图方差)`——16 只是噪声带下限，
    /// 真正起作用的是整图方差（依据见 [`PoolTex::global_var`] 注释与
    /// tests::black_bias_real_samples_v041 的实测：5 个爆炸样本 insideVar
    /// 9560..15610，固定 16 托底后 adjusted 仍有 370..780，必须托到与图
    /// 自身信息量同尺度才能落回 <30）。
    pub out_floor_min: f64,
    /// 岛外亮度均值 < 8/255（≈3% 亮度）且方差 < 16（std≤4，0..255 亮度上
    /// 视觉上仍是均匀黑）→ 判「近纯黑底」。方差线的依据：全库实测
    /// score>30 的爆炸候选里，836 个岛外方差落在 [4,16)——BC3 块压缩+
    /// 边缘溢色让「纯黑」抖动到 std 2..4，旧线（<4）漏掉这一带；方差
    /// ≥16（std>4）开始可能是真实的平淡绘画内容（实测该带 449 个爆炸
    /// 候选），不再外扩。正常绘画内容方差数百起，不误伤。
    pub black_out_mean_max: f64,
    pub black_out_var_max: f64,
    /// 对称的近纯白线（255−8）：溢白垫底与溢黑垫底是同一种病。
    pub white_out_mean_min: f64,
    pub white_out_var_max: f64,
    /// alphaFit 阈值（0..255 尺度）：岛外 alpha 均值 ≤8 → 岛外近全透明
    /// （镂空 cutout 的结构信号）；岛内 ≥200 → 近不透明（对齐）；
    /// 岛内 ≤32 → 岛基本落在透明洞里（强惩罚）。8/200/32 分别对应
    /// 3%/78%/12.5% 不透明度，是「块压缩噪声 / 实心画 / 半透以上」的
    /// 经验分界，未人工校准。
    pub alpha_out_transparent: f64,
    pub alpha_in_opaque: f64,
    pub alpha_hole: f64,
    /// adjustedScore = 修正方差比 × (base + span×sizeFit) × (base + span×alphaFit)。
    /// sizeFit=1/alphaFit=1（主流候选）时乘数恰为 1，adjustedScore 退化为
    /// 旧 score——这是有意的：v2 只在「有证据要修正」时才动 v1 的分。
    pub size_damp_base: f64,
    pub size_damp_span: f64,
    pub alpha_damp_base: f64,
    pub alpha_damp_span: f64,
}

/// v0.4.1 默认参数。sizeFit 的经验档位锚点表见 [`SIZE_FIT_ANCHORS`]。
pub const FACTOR_PARAMS: FactorParams = FactorParams {
    uv_sat_scale: 8.0,
    out_floor_min: 16.0,
    black_out_mean_max: 8.0,
    black_out_var_max: 16.0,
    white_out_mean_min: 247.0,
    white_out_var_max: 16.0,
    alpha_out_transparent: 8.0,
    alpha_in_opaque: 200.0,
    alpha_hole: 32.0,
    size_damp_base: 0.6,
    size_damp_span: 0.4,
    alpha_damp_base: 0.7,
    alpha_damp_span: 0.3,
};

/// sizeFit 经验档位锚点 (log2(边长), fit)：128→0.25、256→0.5、512→1.0、
/// 2048→1.0、4096→0.8、8192→0.4。512..=2048 是角色贴图的惯例尺寸（池先验
/// 本身就 ≥512），给满分；再往上的超大图和往下的碎图都是少数，降档。
/// 档间按 log2 线性插值——尺寸是倍频程量，log 空间比线性空间过渡平缓。
/// **经验档位，未人工校准**。池查询已限 ≥512，低段锚点只对合成测试生效。
const SIZE_FIT_ANCHORS: [(f64, f64); 6] =
    [(7.0, 0.25), (8.0, 0.5), (9.0, 1.0), (11.0, 1.0), (12.0, 0.8), (13.0, 0.4)];

/// root 目录下全部 pak 的只读集合 + `hash → (pak 名, 记录)` 索引。
/// `Pak` 内部是 mmap（只读），`payload::decode` 是纯函数，所以整包
/// `Arc` 起来给分片线程共享没有并发问题。
pub struct PakSet {
    pub paks: HashMap<String, Pak>,
    pub by_hash: HashMap<u64, (String, Record)>,
}

/// 按 `hash` 取出解密解压后的完整字节。取不到 = 记录缺失或解码失败，
/// 调用方按「这张没有」处理，不重试。
pub fn fetch(
    paks: &HashMap<String, Pak>,
    by_hash: &HashMap<u64, (String, Record)>,
    hash: u64,
) -> Option<Vec<u8>> {
    let (name, rec) = by_hash.get(&hash)?;
    let pak = paks.get(name)?;
    payload::decode(pak, rec).ok().map(|d| d.bytes)
}

impl PakSet {
    pub fn fetch(&self, hash: u64) -> Option<Vec<u8>> {
        fetch(&self.paks, &self.by_hash, hash)
    }
}

/// 打开 root 下所有 `.pak`（大小写不敏感），建 hash 索引。同一 hash 多处
/// 出现时取先遇到的（与 bin 版一致，不追求唯一性）。
pub fn open_paks(root: &Path) -> PakSet {
    let mut paks = HashMap::new();
    let mut by_hash: HashMap<u64, (String, Record)> = HashMap::new();
    let Ok(rd) = std::fs::read_dir(root) else {
        return PakSet { paks, by_hash };
    };
    for e in rd.flatten() {
        let p = e.path();
        let is_pak = p
            .extension()
            .map(|x| x.eq_ignore_ascii_case("pak"))
            .unwrap_or(false);
        if !is_pak {
            continue;
        }
        let name = p.file_stem().unwrap_or_default().to_string_lossy().into_owned();
        let Ok(pak) = Pak::open(&p) else { continue };
        for rec in pak.records() {
            if rec.original > 0 {
                by_hash.entry(rec.hash).or_insert((name.clone(), rec));
            }
        }
        paks.insert(name, pak);
    }
    PakSet { paks, by_hash }
}

/// 池的一行 SQL 元数据（解码前的形态，方便先报池规模再解码）。
pub struct PoolRow {
    pub hash: u64,
    pub w: u16,
    pub h: u16,
    pub codec: String,
    pub mips: u32,
}

/// 匿名贴图池的 SQL 查询。条件与排序都是冻结口径：`order by original desc`
/// 决定了同分候选的稳定次序，动它就动了对拍。
pub fn query_pool(con: &Connection, limit: usize) -> Vec<PoolRow> {
    let mut stmt = con
        .prepare(
            "select hash, width, height, codec, mips from resources
             where type='texture' and path is null and width>=512 and height>=512
               and codec in ('RGBA32','BC3') and mips>=4 order by original desc",
        )
        .unwrap();
    let rows = stmt
        .query_map([], |r| {
            let h: String = r.get(0)?;
            Ok(PoolRow {
                hash: u64::from_str_radix(&h, 16).unwrap_or(0),
                w: r.get::<_, i64>(1)? as u16,
                h: r.get::<_, i64>(2)? as u16,
                codec: r.get::<_, String>(3)?,
                mips: r.get::<_, i64>(4)? as u32,
            })
        })
        .unwrap();
    rows.flatten().take(limit).collect()
}

/// 池内一张贴图的内存形态。`w/h/codec/mips` 来自 SQL 行（对外报告口径），
/// `lum` 是解码后按**解码尺寸**盒式降采样的 256² 亮度——旧 score 只用它。
/// v0.4.1 新增 `alpha/color/global_var` 三条证据通道：它们**只喂给 factors**，
/// 与 `lum` 的计算互不相干（lum 仍由 [`downsample`] 从原 RGBA 一步算出），
/// 所以动这三条通道不影响对拍。
pub struct PoolTex {
    pub hash: String,
    pub w: u16,
    pub h: u16,
    pub codec: String,
    pub mips: u32,
    pub lum: Vec<f32>,
    /// 256² alpha 均值（0..255，与 lum 同一降采样几何，见
    /// [`downsample_rgba_stats`]）。池纹理没有真 alpha 通道（解码为 BC1/L8
    /// ——解码器对它们伪造不透明 alpha）时为 None，alphaFit 如实回 null。
    /// BC3/RGBA32 的通道即使全不透明也如实保留（判断交给均值公式）。
    pub alpha: Option<Vec<u8>>,
    /// 256² RGB 均值，`meanColor` 的原始证据来源（不给分）。
    pub color: Vec<[u8; 3]>,
    /// 整图亮度方差（256² 全像素、岛内外一起算）。黑底/白底托底的依据：
    /// 岛外近纯黑时「岛外方差」完全无信息——一个随机放错位置的岛在本图上
    /// 能看到的方差 ≈ 整图方差，所以方差比最保守的分母是它，而不是拍脑袋
    /// 的固定常数。实测 decal.mesh（覆盖满格）top1 insideVar=15610，固定
    /// 16 托底后 adjusted 仍 780；托到整图方差后 ≈1.0，落回合理区间。
    pub global_var: f64,
}

/// 把 SQL 查好的池行解码 + 降采样成可复用的内存池。
/// 整个批量进程只该调一次；`progress(done, total)` 每 200 张回调一次，
/// 让 CLI 保留原有的进度打印节奏。解码失败/长度对不上的张数直接跳过
/// （与 bin 版一致：池里少几张不影响其余候选的评分）。
pub fn decode_pool(
    rows: &[PoolRow],
    paks: &HashMap<String, Pak>,
    by_hash: &HashMap<u64, (String, Record)>,
    progress: &mut dyn FnMut(usize, usize),
) -> Vec<PoolTex> {
    let total = rows.len();
    let mut out = Vec::with_capacity(total);
    for (i, row) in rows.iter().enumerate() {
        let Some(bytes) = fetch(paks, by_hash, row.hash) else {
            continue;
        };
        let Ok(tex) = crate::jmt1::decode(&bytes) else {
            continue;
        };
        if tex.rgba.len() < tex.width as usize * tex.height as usize * 4 {
            continue;
        }
        // v0.4.1 证据通道：alpha 有无由**解码出的实际编码**决定（池 SQL 行的
        // codec 列只会写 RGBA32/BC3，但 BC3 标签会骗人——实际载荷可能是
        // BC1/L8，解码器对它们伪造不透明 alpha，不能当真通道用）。
        let has_alpha = matches!(
            tex.codec,
            crate::jmt1::Codec::Bc3
                | crate::jmt1::Codec::Rgba32
                | crate::jmt1::Codec::Rgba32Bordered
        );
        let lum = downsample(&tex.rgba, tex.width as usize, tex.height as usize);
        let global_var = global_variance(&lum);
        let (alpha, color) = downsample_rgba_stats(
            &tex.rgba,
            tex.width as usize,
            tex.height as usize,
            has_alpha,
        );
        out.push(PoolTex {
            hash: format!("{:016x}", row.hash),
            w: row.w,
            h: row.h,
            codec: row.codec.clone(),
            mips: row.mips,
            lum,
            alpha,
            color,
            global_var,
        });
        if (i + 1) % 200 == 0 {
            progress(i + 1, total);
        }
    }
    out
}

/// 一条评分结果。`inside_var/outside_var/score` 的展示格式冻结在
/// [`Cand::summary`]（候选缓存 JSON 的契约字段）。v0.4.1 在此之上追加
/// `factors`/`adjusted_score`（[`Cand::summary_v2`]，追加式演进：旧字段
/// 一个都不动，只许在尾部加）。
pub struct Cand {
    pub hash: String,
    pub w: u16,
    pub h: u16,
    pub codec: String,
    pub mips: u32,
    pub inside_var: f64,
    pub outside_var: f64,
    pub score: f64,
    /// v0.4.1 因子面板（系统评分口径，不是正确率——见 [`Factors`]）。
    pub factors: Factors,
    /// v0.4.1 聚合分：`修正方差比 × (0.6+0.4×sizeFit) × (0.7+0.3×alphaFit)`
    /// ，公式与常量依据见 [`score_pool`] 与 [`FACTOR_PARAMS`]。无黑底/白底
    /// 修正且 sizeFit=1、alphaFit 中性时，它逐位等于旧 score。
    pub adjusted_score: f64,
}

/// v0.4.1 每候选因子面板。序列化名是落盘契约（camelCase），只许追加不许
/// 改名。三个 fit ∈ 0..1；adjustedScore 的聚合公式：
///
/// ```text
/// corrected = insideVar / (max(outsideVar, 16, 整图方差) + 4)   // 仅黑/白底时托底
/// adjustedScore = corrected × (0.6 + 0.4×sizeFit) × (0.7 + 0.3×alphaFit)
/// ```
#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Factors {
    /// UV 几何匹配：**修正后**的方差比过饱和曲线 `1 - 1/(1 + ratio/8)`。
    /// 用修正比而不是原始 score——黑底虚高时原始比已无意义，若仍按原始比
    /// 归一，uvFit 会饱和到 1.0、与 adjustedScore 的托底口径自相矛盾。
    pub uv_fit: f64,
    /// Alpha 匹配（0..1）。池纹理无真 alpha 通道（解码为 BC1/L8）时为
    /// null——没有通道就直说没有。有通道时的取值：岛外近全透明且岛内近
    /// 不透明（镂空完美对齐）→ 1.0；岛落在透明洞里 → 0.0；其余（双方都
    /// 可见，alpha 无区分信息）→ 中性 1.0。聚合乘数 (0.7+0.3×a) 在中性处
    /// 恰为 1，所以 alpha 通道只在「真的有话要说」时才动分数。
    pub alpha_fit: Option<f64>,
    /// 纹理尺寸适配（经验档位，未人工校准，见 [`SIZE_FIT_ANCHORS`]）。
    pub size_fit: f64,
    /// 黑底修正核心：岛外近纯黑（均值<8 且方差<16；岛外 0 像素时均值按 0
    /// 记，同样成立——「岛外无内容」与「岛外纯黑」对方差比是同一件事：
    /// 分母无信息）。true 时 adjustedScore 的分母托底到 max(16, 整图方差)。
    pub black_bias: bool,
    /// 对称的近纯白修正（均值>247 且方差<4）。
    pub white_bias: bool,
    /// 目录语义占位：匿名池 `path IS NULL`，没有目录信息可依据——无数据
    /// 来源，v0.4.1 不参与 adjustedScore，留给目录语义接上后启用。
    /// （没有就直说没有，不编。）
    pub color_semantics: Option<f64>,
    /// 格式占位：匿名池只有 RGBA32/BC3 两种编码，而这本来就是池的筛选
    /// 先验、不是证据——格式信息弱到给分就是编，v0.4.1 恒 null，不参与
    /// adjustedScore。
    pub format_fit: Option<f64>,
    /// 岛内平均 RGB（原始证据，不给分）。
    pub mean_color: [u8; 3],
}

impl Cand {
    /// 候选缓存的 JSON 片段格式。**这是 UI 契约**：bin 版 --emit-cache 与
    /// 批量版 results/*.json 共用，字段名和精度（{:.1}/{:.3}）不许变。
    pub fn summary(&self) -> String {
        format!(
            "{{\"hash\":\"{}\",\"w\":{},\"h\":{},\"codec\":\"{}\",\"mips\":{},\"insideVar\":{:.1},\"outsideVar\":{:.1},\"score\":{:.3}}}",
            self.hash, self.w, self.h, self.codec, self.mips, self.inside_var, self.outside_var, self.score
        )
    }

    /// v2 版候选 JSON：旧字段（[`Self::summary`]）逐位不动，尾部追加
    /// `factors` 与 `adjustedScore`。批量版 results/*.json 用它；单跑版
    /// --emit-cache 仍用 [`Self::summary`]（逐位契约，不追加）。
    pub fn summary_v2(&self) -> String {
        format!(
            "{{{},\"factors\":{},\"adjustedScore\":{:.3}}}",
            self.summary()
                .trim_start_matches('{')
                .trim_end_matches('}'),
            serde_json::to_string(&self.factors).unwrap_or_else(|_| "{}".into()),
            self.adjusted_score
        )
    }
}

/// 对整个池给一张 mask 评分，按 **旧 score** 降序（排序口径冻结——v2 的
/// adjustedScore 不参与排序，只作为另一个观察口径落在字段里）。
///
/// `ivar <= 0` 的跳过（岛内没有内容或方差非正时没有可比性——bin 版同口径）。
///
/// v0.4.1 每候选额外产出：
/// - `factors`：见 [`Factors`]，常量见 [`FACTOR_PARAMS`]；
/// - `adjustedScore = corrected × (0.6+0.4×sizeFit) × (0.7+0.3×alphaFit)`，
///   其中 `corrected = insideVar / (denominator + 4)`，分母在黑底/白底判定
///   成立时托到 `max(outsideVar, 16, 整图方差)`，否则就是原 outsideVar
///   （此时 corrected 与旧 score 逐位相同）。
pub fn score_pool(mask: &[u8], pool: &[PoolTex]) -> Vec<Cand> {
    let mut results = Vec::new();
    for tex in pool {
        let st = island_stats(
            &tex.lum,
            mask,
            tex.alpha.as_deref(),
            Some(tex.color.as_slice()),
        );
        if st.inside_var <= 0.0 {
            continue;
        }
        let score = st.inside_var / (st.outside_var + 4.0);
        let (factors, adjusted_score) = factors_for(tex, &st);
        results.push(Cand {
            hash: tex.hash.clone(),
            w: tex.w,
            h: tex.h,
            codec: tex.codec.clone(),
            mips: tex.mips,
            inside_var: st.inside_var,
            outside_var: st.outside_var,
            score,
            factors,
            adjusted_score,
        });
    }
    results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
    results
}

/// 岛内/岛外的单遍统计：亮度均值+方差（旧口径逐位一致）、alpha 均值
/// （有通道时）、岛内平均 RGB。[`island_variance`] 的超集。
///
/// 亮度累加的循环顺序、加法次序与旧 [`island_variance`] 完全一致——这是
/// 对拍逐位一致的前提，别“顺手优化”。
pub struct IslandStats {
    pub inside_var: f64,
    pub outside_var: f64,
    /// 岛外亮度均值。岛外 0 像素时按 0.0 记（0/0 是 NaN，黑底判定要靠它
    /// 成立：「岛外无内容」与「岛外纯黑」对方差比是同一种无信息）。
    pub outside_mean: f64,
    /// 岛外像素数 <2 的标记（退化情形：方差恒 0，托底判定要看见它）。
    pub outside_degenerate: bool,
    pub inside_alpha_mean: Option<f64>,
    pub outside_alpha_mean: Option<f64>,
    pub mean_color: [u8; 3],
}

pub fn island_stats(
    lum: &[f32],
    mask: &[u8],
    alpha: Option<&[u8]>,
    color: Option<&[[u8; 3]]>,
) -> IslandStats {
    let mut si = (0f64, 0f64, 0u64);
    let mut so = (0f64, 0f64, 0u64);
    let mut sa = (0f64, 0f64, 0u64); // alpha：岛内/岛外均值
    let mut sc = (0f64, 0f64, 0f64); // 岛内 RGB 累计
    for (i, &m) in mask.iter().enumerate() {
        let v = lum[i] as f64;
        if m == 1 {
            si.0 += v;
            si.1 += v * v;
            si.2 += 1;
            if let Some(a) = alpha {
                let av = a[i] as f64;
                sa.0 += av;
                sa.1 += 1.0;
            }
            if let Some(c) = color {
                sc.0 += c[i][0] as f64;
                sc.1 += c[i][1] as f64;
                sc.2 += c[i][2] as f64;
            }
        } else {
            so.0 += v;
            so.1 += v * v;
            so.2 += 1;
            if let Some(a) = alpha {
                sa.1 += a[i] as f64;
            }
        }
    }
    let var = |s: (f64, f64, u64)| {
        if s.2 < 2 {
            0.0
        } else {
            let mean = s.0 / s.2 as f64;
            (s.1 / s.2 as f64) - mean * mean
        }
    };
    // alpha 的 sa 元组借用了 var 的形状：sa.0=岛内累计，sa.1=岛外累计，
    // sa.2=岛内计数；计数 <1 时均值按 0 记（岛内为 0 的情形已在调用方
    // 被 ivar<=0 过滤，这里只是防御）。
    let amean = |sum: f64, n: u64| if n == 0 { 0.0 } else { sum / n as f64 };
    let (ia, oa) = match alpha {
        Some(_) => (
            Some(amean(sa.0, si.2)),
            Some(amean(sa.1, so.2)),
        ),
        None => (None, None),
    };
    let n = si.2 as f64;
    let mean_color = if n > 0.0 {
        [
            (sc.0 / n).round().clamp(0.0, 255.0) as u8,
            (sc.1 / n).round().clamp(0.0, 255.0) as u8,
            (sc.2 / n).round().clamp(0.0, 255.0) as u8,
        ]
    } else {
        [0, 0, 0]
    };
    IslandStats {
        inside_var: var(si),
        outside_var: var(so),
        outside_mean: if so.2 == 0 { 0.0 } else { so.0 / so.2 as f64 },
        outside_degenerate: so.2 < 2,
        inside_alpha_mean: ia,
        outside_alpha_mean: oa,
        mean_color,
    }
}

/// 岛内 / 岛外亮度方差。真被画过的贴图：岛内是绘画细节（高方差），
/// 岛外是溢色垫底（低方差）。保留旧签名（对拍测试直接调它），实现委托
/// 给 [`island_stats`]（亮度累加路径逐位一致）。
pub fn island_variance(lum: &[f32], mask: &[u8]) -> (f64, f64) {
    let st = island_stats(lum, mask, None, None);
    (st.inside_var, st.outside_var)
}

/// v0.4.1 因子面板 + adjustedScore 聚合。公式（常量见 [`FACTOR_PARAMS`]）：
///
/// ```text
/// biased   = blackBias || whiteBias
/// floored  = max(outsideVar, 16, 整图方差)          // 仅 biased 时
/// corrected    = insideVar / ((biased ? floored : outsideVar) + 4)
/// uvFit        = 1 - 1/(1 + corrected/8)
/// adjustedScore = corrected × (0.6+0.4×sizeFit) × (alphaFit 有值 ? 0.7+0.3×alphaFit : 1)
/// ```
fn factors_for(tex: &PoolTex, st: &IslandStats) -> (Factors, f64) {
    let p = &FACTOR_PARAMS;
    // 黑底/白底判定。岛外退化（<2 像素，方差恒 0、均值无意义）时：
    // 0 像素 → outside_mean 按 0 记 → 落黑底；1 像素按实际亮度判。
    let black_bias =
        st.outside_mean < p.black_out_mean_max && st.outside_var < p.black_out_var_max;
    let white_bias =
        st.outside_mean > p.white_out_mean_min && st.outside_var < p.white_out_var_max;
    let biased = black_bias || white_bias;
    // 托底：最低 16（规格示例值，噪声带下限），再与整图方差取 max——
    // 岛外无信息时分母的保守估计是「随机岛在本图上能看到的方差」。
    // 未判 biased 时完全不托底（corrected 与旧 score 逐位相同）。
    let denom_out = if biased {
        st.outside_var.max(p.out_floor_min).max(tex.global_var)
    } else {
        st.outside_var
    };
    let corrected = st.inside_var / (denom_out + 4.0);
    let uv_fit = 1.0 - 1.0 / (1.0 + corrected / p.uv_sat_scale);
    let size_fit = size_fit_curve(tex.w.min(tex.h));
    let alpha_fit = alpha_fit_factor(st);
    let size_damp = p.size_damp_base + p.size_damp_span * size_fit;
    let alpha_damp = alpha_fit.map_or(1.0, |a| p.alpha_damp_base + p.alpha_damp_span * a);
    let adjusted = corrected * size_damp * alpha_damp;
    (
        Factors {
            uv_fit,
            alpha_fit,
            size_fit,
            black_bias,
            white_bias,
            // 占位：无数据来源不编数，见 Factors 字段注释。
            color_semantics: None,
            format_fit: None,
            mean_color: st.mean_color,
        },
        adjusted,
    )
}

/// alphaFit（见 [`Factors::alpha_fit`]）。`inside_alpha_mean` 为 None 即池
/// 纹理无真 alpha 通道 → 如实回 None。
fn alpha_fit_factor(st: &IslandStats) -> Option<f64> {
    let p = &FACTOR_PARAMS;
    let imean = st.inside_alpha_mean?;
    let omean = st.outside_alpha_mean?;
    if omean <= p.alpha_out_transparent {
        // 岛外近全透明 → 镂空贴图，岛内可见度就是对齐度：
        // 完全对齐（岛罩住实心画）→ 1.0；岛落在洞里 → 0.0；中间线性。
        if imean >= p.alpha_in_opaque {
            return Some(1.0);
        }
        if imean <= p.alpha_hole {
            return Some(0.0);
        }
        return Some((imean - p.alpha_hole) / (p.alpha_in_opaque - p.alpha_hole));
    }
    if imean <= p.alpha_hole {
        // 岛外不透明但岛自己落在近全透明洞里（贴图中央镂空被岛罩住）
        // → 渲染出来就是空的，强惩罚。
        return Some(0.0);
    }
    // 其余：内外都可见，alpha 无区分信息 → 中性 1.0（乘数恰为 1）。
    // 「岛内 vs 岛外均值差」在这个分支刻意不用：双方都不透明时差值是
    // 块压缩噪声，拿它给分就是编信号。
    Some(1.0)
}

/// sizeFit 经验曲线（锚点见 [`SIZE_FIT_ANCHORS`]，log2 空间分段线性，
/// 端外钳位）。取 min(w,h) 为口径——限制尺寸的是短板边。
fn size_fit_curve(min_side: u16) -> f64 {
    let l = (min_side.max(1) as f64).log2();
    let anchors = &SIZE_FIT_ANCHORS;
    if l <= anchors[0].0 {
        return anchors[0].1;
    }
    let last = anchors.len() - 1;
    if l >= anchors[last].0 {
        return anchors[last].1;
    }
    for w in anchors.windows(2) {
        let ((l0, f0), (l1, f1)) = (w[0], w[1]);
        if l <= l1 {
            return f0 + (f1 - f0) * (l - l0) / (l1 - l0);
        }
    }
    anchors[last].1
}

/// 256² 整图亮度方差（f64 累加，与 [`island_stats`] 的 var 同款公式）。
pub fn global_variance(lum: &[f32]) -> f64 {
    let mut s = 0f64;
    let mut sq = 0f64;
    for &v in lum {
        let v = v as f64;
        s += v;
        sq += v * v;
    }
    if lum.len() < 2 {
        return 0.0;
    }
    let n = lum.len() as f64;
    let mean = s / n;
    sq / n - mean * mean
}

/// 与 [`downsample`] 完全相同的步长子采样几何（step、k%step 判定一致），
/// 但采的是 RGB 均值与 alpha 均值——v0.4.1 的新证据通道，不参与旧 score，
/// 改它不影响对拍。`has_alpha=false`（BC1/L8 等无真通道的解码产物）时
/// alpha 返回 None。
pub fn downsample_rgba_stats(
    rgba: &[u8],
    w: usize,
    h: usize,
    has_alpha: bool,
) -> (Option<Vec<u8>>, Vec<[u8; 3]>) {
    let mut a_out = if has_alpha {
        Some(vec![0u8; GRID * GRID])
    } else {
        None
    };
    let mut c_out = vec![[0u8; 3]; GRID * GRID];
    for gy in 0..GRID {
        let y0 = gy * h / GRID;
        let y1 = ((gy + 1) * h / GRID).max(y0 + 1);
        for gx in 0..GRID {
            let x0 = gx * w / GRID;
            let x1 = ((gx + 1) * w / GRID).max(x0 + 1);
            let step = ((x1 - x0) * (y1 - y0) / 16).max(1);
            let (mut ar, mut ag, mut ab, mut aa, mut n) = (0f64, 0f64, 0f64, 0f64, 0u64);
            let mut k = 0usize;
            for y in y0..y1 {
                for x in x0..x1 {
                    if k % step == 0 {
                        let o = (y * w + x) * 4;
                        if o + 3 < rgba.len() {
                            ar += rgba[o] as f64;
                            ag += rgba[o + 1] as f64;
                            ab += rgba[o + 2] as f64;
                            if has_alpha {
                                aa += rgba[o + 3] as f64;
                            }
                            n += 1;
                        }
                    }
                    k += 1;
                }
            }
            if n > 0 {
                let cell = gy * GRID + gx;
                c_out[cell] = [
                    (ar / n as f64).round().clamp(0.0, 255.0) as u8,
                    (ag / n as f64).round().clamp(0.0, 255.0) as u8,
                    (ab / n as f64).round().clamp(0.0, 255.0) as u8,
                ];
                if let Some(a) = a_out.as_mut() {
                    a[cell] = (aa / n as f64).round().clamp(0.0, 255.0) as u8;
                }
            }
        }
    }
    (a_out, c_out)
}

/// UV 三角形栅格化成 256² 岛内 mask（岛内 = 1）。返回 (mask, 有效三角形数)。
/// 索引越界的三角形跳过（bin 版同口径，不panic也不夹断）。
pub fn build_mask(uvs: &[[f32; 2]], indices: &[u16]) -> (Vec<u8>, usize) {
    let mut mask = vec![0u8; GRID * GRID];
    let mut tris = 0usize;
    for t in indices.chunks_exact(3) {
        let (ia, ib, ic) = (t[0] as usize, t[1] as usize, t[2] as usize);
        if ia >= uvs.len() || ib >= uvs.len() || ic >= uvs.len() {
            continue;
        }
        rasterize(&mut mask, uvs[ia], uvs[ib], uvs[ic]);
        tris += 1;
    }
    (mask, tris)
}

/// mask 里被岛覆盖的像素数。
pub fn covered(mask: &[u8]) -> usize {
    mask.iter().filter(|&&m| m == 1).count()
}

/// 三角形用包围盒 + 重心坐标填充。判定阈值 -0.001 是 bin 版冻结口径
/// （盖住像素中心点，含极薄三角形）。
pub fn rasterize(mask: &mut [u8], a: [f32; 2], b: [f32; 2], c: [f32; 2]) {
    let g = GRID as f32;
    let (ax, ay) = (a[0] * g, a[1] * g);
    let (bx, by) = (b[0] * g, b[1] * g);
    let (cx, cy) = (c[0] * g, c[1] * g);
    let minx = ax.min(bx).min(cx).floor().max(0.0) as i32;
    let maxx = ax.max(bx).max(cx).ceil().min(g - 1.0) as i32;
    let miny = ay.min(by).min(cy).floor().max(0.0) as i32;
    let maxy = ay.max(by).max(cy).ceil().min(g - 1.0) as i32;
    let det = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
    if det.abs() < 1e-9 {
        return;
    }
    for y in miny..=maxy {
        for x in minx..=maxx {
            let (px, py) = (x as f32 + 0.5, y as f32 + 0.5);
            let w1 = ((px - ax) * (cy - ay) - (py - ay) * (cx - ax)) / det;
            let w2 = ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / det;
            let w0 = 1.0 - w1 - w2;
            if w0 >= -0.001 && w1 >= -0.001 && w2 >= -0.001 {
                mask[(y * GRID as i32 + x) as usize] = 1;
            }
        }
    }
}

/// 盒式降采样到 GRID×GRID 的亮度（0..255）。步长子采样（每 16 像素取 1）
/// 是 bin 版冻结口径——它不追求统计精确，只要求**每次都一样**。
pub fn downsample(rgba: &[u8], w: usize, h: usize) -> Vec<f32> {
    let mut out = vec![0f32; GRID * GRID];
    for gy in 0..GRID {
        let y0 = gy * h / GRID;
        let y1 = ((gy + 1) * h / GRID).max(y0 + 1);
        for gx in 0..GRID {
            let x0 = gx * w / GRID;
            let x1 = ((gx + 1) * w / GRID).max(x0 + 1);
            let mut acc = 0f64;
            let mut n = 0u64;
            let step = ((x1 - x0) * (y1 - y0) / 16).max(1);
            let mut k = 0usize;
            for y in y0..y1 {
                for x in x0..x1 {
                    if k % step == 0 {
                        let o = (y * w + x) * 4;
                        if o + 2 < rgba.len() {
                            acc += 0.299 * rgba[o] as f64 + 0.587 * rgba[o + 1] as f64
                                + 0.114 * rgba[o + 2] as f64;
                            n += 1;
                        }
                    }
                    k += 1;
                }
            }
            out[gy * GRID + gx] = if n > 0 { (acc / n as f64) as f32 } else { 0.0 };
        }
    }
    out
}

/// mesh 文件名 → hash。与 bin 版同一套查询口径：`path like '%/<name>'`
/// 取第一条（同名多份时选谁由库的物理顺序决定，沿用即是对拍口径）。
pub fn mesh_hash(con: &Connection, mesh: &str) -> Option<u64> {
    con.query_row(
        "select hash from resources where lower(path) like '%/' || lower(?1) limit 1",
        [mesh],
        |r| {
            let s: String = r.get(0)?;
            Ok(u64::from_str_radix(&s, 16).unwrap_or(0))
        },
    )
    .ok()
}

/// 全部 `.mdl` 引用过的 mesh 文件名（已按文件名去重）。
/// `refs` 的 `.mesh` 行是 .mdl 文件体里声明的成员引用——「模型清单以
/// .mdl 的成员 mesh 为准」就落在它上面；个别行 to_hash 解析不了，但文件名
/// 仍在，交给 [`mesh_hash`] 用与 bin 版相同的口径再解一次。
pub fn mdl_mesh_names(con: &Connection) -> Vec<String> {
    let mut stmt = con
        .prepare(
            "select distinct name from refs
             where kind='.mesh' and lower(from_path) like '%.mdl' order by name",
        )
        .unwrap();
    stmt.query_map([], |r| r.get::<_, String>(0))
        .unwrap()
        .flatten()
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::preview::parse_geometry;

    /// 合成 mask + 亮度，验证方差与得分的数学口径（不依赖真库数据，
    /// 常规 `cargo test` 就能跑）。手算：岛内 4 像素 {10,20,30,40}，
    /// 岛外 4 像素 {0,0,0,0}。
    #[test]
    fn variance_and_score_math() {
        let mut mask = vec![0u8; GRID * GRID];
        for i in 0..4 {
            mask[i] = 1;
        }
        let mut lum = vec![0f32; GRID * GRID];
        for (i, v) in [10f32, 20.0, 30.0, 40.0].into_iter().enumerate() {
            lum[i] = v;
        }
        let (ivar, ovar) = island_variance(&lum, &mask);
        // 均值 25，方差 (225+25+25+225)/4 = 125；岛外全 0 → 方差 0。
        assert!((ivar - 125.0).abs() < 1e-9, "ivar={ivar}");
        assert_eq!(ovar, 0.0);
        let score = ivar / (ovar + 4.0);
        assert!((score - 31.25).abs() < 1e-9, "score={score}");
    }

    /// summary() 的字段名与精度是候选缓存 JSON 的 UI 契约，锁死。
    /// 注意 score 直接给定值而不从 insideVar/outsideVar 现算——旧缓存里
    /// 打印的 inside/outside 是 {:.1} 舍入后的展示值，真实分数来自未舍入
    /// 的内部值（654.5/140.7 = 4.6517 → 4.652，但旧缓存是 4.651），这也
    /// 正是对拍必须比 score 原值而不是复算展示值的原因。
    /// v0.4.1 给 Cand 加了 factors/adjusted_score 字段，但 summary() 输出
    /// 一个字符都不能变（v2 字段只出现在 summary_v2() 里）。
    #[test]
    fn cand_summary_format_is_frozen() {
        let c = Cand {
            hash: "ca50d2c1f95dd98c".into(),
            w: 512,
            h: 512,
            codec: "BC3".into(),
            mips: 10,
            inside_var: 654.46,
            outside_var: 136.72,
            score: 4.651,
            factors: Factors {
                uv_fit: 0.367,
                alpha_fit: None,
                size_fit: 1.0,
                black_bias: false,
                white_bias: false,
                color_semantics: None,
                format_fit: None,
                mean_color: [0, 0, 0],
            },
            adjusted_score: 4.651,
        };
        assert_eq!(
            c.summary(),
            "{\"hash\":\"ca50d2c1f95dd98c\",\"w\":512,\"h\":512,\"codec\":\"BC3\",\"mips\":10,\"insideVar\":654.5,\"outsideVar\":136.7,\"score\":4.651}"
        );
    }

    /// summary_v2() 是追加式演进：旧字段逐位在前，尾部追加 factors 与
    /// adjustedScore。字段名是批量落盘的契约，锁死一份样例。
    #[test]
    fn cand_summary_v2_appends_only() {
        let c = Cand {
            hash: "ca50d2c1f95dd98c".into(),
            w: 512,
            h: 512,
            codec: "BC3".into(),
            mips: 10,
            inside_var: 654.46,
            outside_var: 136.72,
            score: 4.651,
            factors: Factors {
                uv_fit: 0.367,
                alpha_fit: None,
                size_fit: 1.0,
                black_bias: false,
                white_bias: false,
                color_semantics: None,
                format_fit: None,
                mean_color: [212, 45, 38],
            },
            adjusted_score: 4.651,
        };
        assert_eq!(
            c.summary_v2(),
            "{\"hash\":\"ca50d2c1f95dd98c\",\"w\":512,\"h\":512,\"codec\":\"BC3\",\"mips\":10,\"insideVar\":654.5,\"outsideVar\":136.7,\"score\":4.651,\"factors\":{\"uvFit\":0.367,\"alphaFit\":null,\"sizeFit\":1.0,\"blackBias\":false,\"whiteBias\":false,\"colorSemantics\":null,\"formatFit\":null,\"meanColor\":[212,45,38]},\"adjustedScore\":4.651}"
        );
    }

    /// 全零 mask（无有效 UV）时岛内方差为 0 → 评分全跳过 → 无候选。
    #[test]
    fn empty_mask_yields_no_candidates() {
        let pool = vec![PoolTex {
            hash: "ab".into(),
            w: 512,
            h: 512,
            codec: "BC3".into(),
            mips: 4,
            lum: vec![128f32; GRID * GRID],
            alpha: None,
            color: vec![[0, 0, 0]; GRID * GRID],
            global_var: 0.0,
        }];
        let mask = vec![0u8; GRID * GRID];
        assert!(score_pool(&mask, &pool).is_empty());
    }

    /// 合成 PoolTex 的小工具：256² 亮度 + 可选 alpha（0/255 两值）。
    fn synth_tex(hash: &str, lum: Vec<f32>, alpha: Option<Vec<u8>>) -> PoolTex {
        let global_var = global_variance(&lum);
        PoolTex {
            hash: hash.into(),
            w: 512,
            h: 512,
            codec: "BC3".into(),
            mips: 10,
            lum,
            alpha,
            color: vec![[0, 0, 0]; GRID * GRID],
            global_var,
        }
    }

    /// v0.4.1 核心验收（合成）：黑底稀疏亮块——岛外近纯黑 → blackBias
    /// 触发，adjustedScore 从爆炸值（旧 score=ivar/4）落回合理区间。
    /// 手算：岛内 {30,220} 棋盘 → ivar=9025，岛外全 0 → 旧 score=2256.25；
    /// 整图方差 = 0.5·((900+48400)/2) − (0.5·125)² = 8418.75，
    /// adjusted = 9025/(8418.75+4) ≈ 1.071。
    #[test]
    fn black_bias_triggers_and_floor_brings_score_back() {
        let mut lum = vec![0f32; GRID * GRID];
        let mut mask = vec![0u8; GRID * GRID];
        for y in 0..GRID {
            for x in 0..GRID {
                let i = y * GRID + x;
                if x < GRID / 2 {
                    mask[i] = 1;
                    lum[i] = if (x + y) % 2 == 0 { 30.0 } else { 220.0 };
                }
            }
        }
        let pool = vec![synth_tex("deadbeef", lum, None)];
        let scored = score_pool(&mask, &pool);
        assert_eq!(scored.len(), 1);
        let c = &scored[0];
        assert!((c.score - 2256.25).abs() < 1e-6, "旧 score 逐位口径 {}", c.score);
        assert!(c.factors.black_bias, "黑底判定应触发");
        assert!(!c.factors.white_bias);
        assert!(
            c.adjusted_score < 30.0,
            "adjusted {} 应落回合理区间",
            c.adjusted_score
        );
        assert!((c.adjusted_score - 9025.0 / (8418.75 + 4.0)).abs() < 1e-6);
        // 修正方差比 ~1.07 → uvFit ≈ 0.118（饱和曲线）。
        assert!((c.factors.uv_fit - (1.0 - 1.0 / (1.0 + c.adjusted_score / 8.0))).abs() < 1e-9);
    }

    /// 对称性：近纯白底同样触发托底（whiteBias），常数对齐 255−8=247。
    #[test]
    fn white_bias_symmetric() {
        let mut lum = vec![255f32; GRID * GRID];
        let mut mask = vec![0u8; GRID * GRID];
        for y in 0..GRID {
            for x in 0..GRID {
                let i = y * GRID + x;
                if x < GRID / 2 {
                    mask[i] = 1;
                    lum[i] = if (x + y) % 2 == 0 { 60.0 } else { 230.0 };
                }
            }
        }
        let pool = vec![synth_tex("feedface", lum, None)];
        let c = &score_pool(&mask, &pool)[0];
        assert!(c.factors.white_bias, "白底判定应触发");
        assert!(!c.factors.black_bias);
        assert!(c.adjusted_score < 30.0, "adjusted {}", c.adjusted_score);
    }

    /// 正常纹理（岛外是真实绘画内容，均值 128、有起伏）：不触发黑/白底，
    /// 且 sizeFit=1、alphaFit=None 时 adjustedScore 与旧 score **逐位相等**
    /// ——v2 只在「有证据要修正」时才动 v1 的分。
    #[test]
    fn normal_texture_adjusted_equals_score() {
        let mut lum = vec![0f32; GRID * GRID];
        let mut mask = vec![0u8; GRID * GRID];
        for y in 0..GRID {
            for x in 0..GRID {
                let i = y * GRID + x;
                mask[i] = if x < GRID / 2 { 1 } else { 0 };
                // 伪随机起伏（确定性，不引依赖）：岛内高对比，岛外中灰微纹。
                let t = ((x * 7 + y * 13) % 11) as f32;
                lum[i] = if x < GRID / 2 { 40.0 + 18.0 * t } else { 120.0 + t };
            }
        }
        let pool = vec![synth_tex("cafe1234", lum, None)];
        let c = &score_pool(&mask, &pool)[0];
        assert!(!c.factors.black_bias && !c.factors.white_bias);
        assert!((c.factors.size_fit - 1.0).abs() < 1e-12);
        assert_eq!(c.factors.alpha_fit, None);
        assert!(
            (c.adjusted_score - c.score).abs() < 1e-9,
            "无修正时 adjusted 应逐位等于 score：{} vs {}",
            c.adjusted_score,
            c.score
        );
    }

    /// alphaFit 三分支：镂空完美对齐 → 1.0；岛落在透明洞里 → 0.0；
    /// 无 alpha 通道（BC1/L8 的解码产物）→ null。岛内亮度给两值棋盘
    /// （ivar>0 才入榜），alpha 讲自己的故事。
    #[test]
    fn alpha_fit_branches() {
        let mut lum = vec![0f32; GRID * GRID];
        let mut mask = vec![0u8; GRID * GRID];
        for y in 0..GRID {
            for x in 0..GRID {
                let i = y * GRID + x;
                mask[i] = if x < GRID / 2 { 1 } else { 0 };
                lum[i] = if x < GRID / 2 {
                    if (x + y) % 2 == 0 { 150.0 } else { 210.0 }
                } else {
                    0.0
                };
            }
        }
        // 镂空对齐：岛外 alpha=0、岛内 alpha=255。
        let mut a_ok = vec![0u8; GRID * GRID];
        for i in 0..GRID * GRID {
            if mask[i] == 1 {
                a_ok[i] = 255;
            }
        }
        let c = &score_pool(&mask, &[synth_tex("a", lum.clone(), Some(a_ok))])[0];
        assert_eq!(c.factors.alpha_fit, Some(1.0));

        // 岛在洞里：岛内也透明。alpha 乘数 0.7 → adjusted 是无 alpha
        // 情形（乘数 1）的 0.7 倍（corrected/sizeDamp 与 alpha 无关）。
        let a_hole = vec![0u8; GRID * GRID];
        let c = &score_pool(&mask, &[synth_tex("b", lum.clone(), Some(a_hole))])[0];
        assert_eq!(c.factors.alpha_fit, Some(0.0));
        let c_none = &score_pool(&mask, &[synth_tex("c", lum.clone(), None)])[0];
        assert!((c.adjusted_score - 0.7 * c_none.adjusted_score).abs() < 1e-6);

        // 部分对齐：岛内 alpha 均值 100 → (100-32)/(200-32) ≈ 0.405。
        let mut a_part = vec![0u8; GRID * GRID];
        for i in 0..GRID * GRID {
            if mask[i] == 1 {
                a_part[i] = 100;
            }
        }
        let c = &score_pool(&mask, &[synth_tex("d", lum, Some(a_part))])[0];
        let f = c.factors.alpha_fit.unwrap();
        assert!(f > 0.3 && f < 0.5, "部分对齐应落在 (0.3,0.5)，得到 {f}");
    }

    /// sizeFit 经验档位：锚点值精确、档间 log2 线性插值。
    #[test]
    fn size_fit_anchors() {
        let f = size_fit_curve;
        assert!((f(512) - 1.0).abs() < 1e-12);
        assert!((f(1024) - 1.0).abs() < 1e-12);
        assert!((f(2048) - 1.0).abs() < 1e-12);
        assert!((f(256) - 0.5).abs() < 1e-12);
        assert!((f(128) - 0.25).abs() < 1e-12);
        assert!((f(4096) - 0.8).abs() < 1e-12);
        assert!((f(8192) - 0.4).abs() < 1e-12);
        // 3072 = 2^11.585：在 1.0(2048) 与 0.8(4096) 之间线性内插。
        let l = (3072f64).log2();
        let want = 1.0 + (0.8 - 1.0) * (l - 11.0);
        assert!((f(3072) - want).abs() < 1e-12);
        // 端外钳位。
        assert!((f(64) - 0.25).abs() < 1e-12);
        assert!((f(16384) - 0.4).abs() < 1e-12);
    }

    /// adjustedScore 排序合理性：黑底上「岛罩住亮块」必须显著高于
    /// 「岛罩住暗噪声」（后者旧 score 也低，但这里验证 v2 排序不被
    /// 托底公式颠倒）。
    #[test]
    fn adjusted_ordering_aligned_above_misaligned() {
        let mut mask = vec![0u8; GRID * GRID];
        for y in 0..GRID {
            for x in 0..GRID {
                if x < GRID / 2 {
                    mask[y * GRID + x] = 1;
                }
            }
        }
        // 对齐：岛内 {30,220} 棋盘，岛外黑。
        let mut lum_a = vec![0f32; GRID * GRID];
        // 错位：亮棋盘摊在岛外，岛内只有 {4,8} 的暗噪声（ivar>0 才入榜）。
        let mut lum_b = vec![0f32; GRID * GRID];
        for y in 0..GRID {
            for x in 0..GRID {
                let i = y * GRID + x;
                if x < GRID / 2 {
                    lum_a[i] = if (x + y) % 2 == 0 { 30.0 } else { 220.0 };
                    lum_b[i] = if (x + y) % 2 == 0 { 4.0 } else { 8.0 };
                } else {
                    lum_b[i] = if (x + y) % 2 == 0 { 30.0 } else { 220.0 };
                }
            }
        }
        let scored = score_pool(&mask, &[synth_tex("a", lum_a, None), synth_tex("b", lum_b, None)]);
        assert_eq!(scored.len(), 2);
        let (a, b) = (&scored[0], &scored[1]);
        assert!(a.hash == "a" && b.hash == "b");
        assert!(a.adjusted_score > 10.0 * b.adjusted_score);
        // a 的岛外是纯黑 → blackBias；b 的岛外是亮棋盘（真内容）→ 不触发，
        // b 的低分来自方差比本身，不需要修正。
        assert!(a.factors.black_bias);
        assert!(!b.factors.black_bias);
    }

    /// 离线对拍（关键回归）：用本机真库复算 3 个生产候选缓存
    /// （`.scratch/texture_candidates/`），Top-N 的 hash 序列与 score 必须
    /// 与旧缓存一致（误差 ≤ 1e-4）。旧缓存是 bin 版（含降采样路径）的
    /// 产物，这条测试保证 lib 化没有改任何数值口径。
    ///
    /// 依赖 D:/TLGL 的 db + pak（约 10s 池解码），默认 #[ignore]，
    /// 手动跑：`cargo test -p tlbb-core --release -- --ignored uvfit`
    #[test]
    #[ignore = "依赖本机 D:/TLGL 真实数据（db/pak/旧缓存），离线对拍时手动跑"]
    fn replay_production_candidate_caches() {
        let root = Path::new("D:/TLGL");
        let db = root.join(".scratch/resources.db");
        let cache_dir = root.join(".scratch/texture_candidates");
        if !db.exists() || !cache_dir.is_dir() {
            eprintln!("本机没有对拍数据（{db:?} / {cache_dir:?}），跳过");
            return;
        }
        let cases = [
            "w1351_monster_xiyuqiezei_shoutao_001",
            "w1351_monster_xiyuqiezei_yifu_001",
            "w1351_wuhun_t_yuyaopan_0102",
        ];
        let set = open_paks(root);
        let con = Connection::open_with_flags(
            &db,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .expect("db 打不开");
        // 池只解一次，三个 mesh 共用——这也是批量版的正确姿势。
        let pool_rows = query_pool(&con, usize::MAX);
        let pool = decode_pool(&pool_rows, &set.paks, &set.by_hash, &mut |_, _| {});

        for stem in cases {
            let raw = std::fs::read_to_string(cache_dir.join(format!("{stem}.json")))
                .expect("旧候选缓存读得到");
            let old: serde_json::Value = serde_json::from_str(&raw).unwrap();
            let mesh = old["mesh"].as_str().unwrap();
            // 旧缓存的 "pool" 记的是 SQL 行数（解码前的口径）。
            assert_eq!(
                pool_rows.len(),
                old["pool"].as_u64().unwrap() as usize,
                "{stem}: 池规模口径"
            );

            let hash = mesh_hash(&con, mesh).expect("网格找不到");
            let bytes = set.fetch(hash).expect("网格字节取不到");
            let geo = parse_geometry(&bytes).expect("网格几何解析失败");
            let (mask, _) = build_mask(&geo.uvs, &geo.indices);
            let cov = covered(&mask) as f64 / (GRID * GRID) as f64;
            // 旧缓存的 coverage 只有 {:.4}，半格容差。
            assert!(
                (cov - old["coverage"].as_f64().unwrap()).abs() < 5e-5,
                "{stem}: coverage {cov} vs {}",
                old["coverage"]
            );

            let scored = score_pool(&mask, &pool);
            let old_cands = old["candidates"].as_array().unwrap();
            assert!(
                scored.len() >= old_cands.len(),
                "{stem}: 新候选 {} 少于旧缓存 {}",
                scored.len(),
                old_cands.len()
            );
            for (i, c) in old_cands.iter().enumerate() {
                assert_eq!(scored[i].hash, c["hash"].as_str().unwrap(), "{stem} 第 {i} 名 hash");
                // 旧缓存里的 score/insideVar/outsideVar 都是 {:.3}/{:.1} 的**展示值**，
                // 原始 f64 与展示值之差最大可到 5e-4（如 2709.506364… → "2709.506"），
                // 所以逐位一致的判据是「两边按同一精度重新渲染出同一字符串」，
                // 而不是拿原始差值对 1e-4——后者对任何按显示精度落盘的基准都必然
                // 失败。（旧值先 parse 回 f64 再重渲染，绕开 JSON 尾零丢失：文件里的
                // "238.750" 经 serde_json 解析再 to_string 会变成 "238.75"。）
                assert_eq!(
                    format!("{:.3}", scored[i].score),
                    format!("{:.3}", c["score"].as_f64().unwrap()),
                    "{stem} 第 {i} 名 score 展示值（新原始 {}）",
                    scored[i].score
                );
                assert_eq!(
                    format!("{:.1}", scored[i].inside_var),
                    format!("{:.1}", c["insideVar"].as_f64().unwrap()),
                    "{stem} 第 {i} 名 insideVar 展示值（新原始 {}）",
                    scored[i].inside_var
                );
                assert_eq!(
                    format!("{:.1}", scored[i].outside_var),
                    format!("{:.1}", c["outsideVar"].as_f64().unwrap()),
                    "{stem} 第 {i} 名 outsideVar 展示值（新原始 {}）",
                    scored[i].outside_var
                );
            }
            eprintln!("对拍通过：{stem}（{} 个候选 hash 序列与三值展示逐位一致）", old_cands.len());
        }
    }

    /// v0.4.1 黑底修正的真实样例验收（规格硬指标）：从批量 manifest 挑的
    /// 5 个 topScore>100 且 graded=high 的爆炸样本，修正后 top1 的
    /// adjustedScore 必须落回 <30，且修正原因是 blackBias=true。
    ///
    /// 依赖 D:/TLGL 的 db + pak（~10s 池解码），默认 #[ignore]，手动跑：
    /// `cargo test -p tlbb-core --release -- --ignored black_bias_real`
    #[test]
    #[ignore = "依赖本机 D:/TLGL 真实数据（db/pak），v0.4.1 验收时手动跑"]
    fn black_bias_real_samples_v041() {
        let root = Path::new("D:/TLGL");
        let db = root.join(".scratch/resources.db");
        if !db.exists() {
            eprintln!("本机没有对拍数据（{db:?}），跳过");
            return;
        }
        // 全部来自 .scratch/uvfit_batch/manifest.json：topScore>100 的 high 档。
        let cases = [
            "decal.mesh",                            // 3902.606
            "chuansong001.mesh",                     // 2882.453
            "w1351_boss_baidiliugui_lian_01.mesh",   // 2846.801
            "w1351_ani_model_lianhua_h001.mesh",     // 2194.462
            "_w1351_boss_sysz_langying_shoutao_001.mesh", // 2120.980
        ];
        let set = open_paks(root);
        let con = Connection::open_with_flags(
            &db,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .expect("db 打不开");
        let pool_rows = query_pool(&con, usize::MAX);
        let pool = decode_pool(&pool_rows, &set.paks, &set.by_hash, &mut |_, _| {});
        for mesh in cases {
            let hash = mesh_hash(&con, mesh).unwrap_or_else(|| panic!("{mesh}: 网格找不到"));
            let bytes = set.fetch(hash).unwrap_or_else(|| panic!("{mesh}: 字节取不到"));
            let geo = parse_geometry(&bytes).unwrap_or_else(|_| panic!("{mesh}: 几何解析失败"));
            let (mask, _) = build_mask(&geo.uvs, &geo.indices);
            let scored = score_pool(&mask, &pool);
            let c = scored
                .first()
                .unwrap_or_else(|| panic!("{mesh}: 无候选"));
            eprintln!(
                "{mesh}: 旧score={:.3} → adjustedScore={:.3} · blackBias={} whiteBias={} uvFit={:.3} alphaFit={:?} sizeFit={:.3} meanColor={:?}",
                c.score,
                c.adjusted_score,
                c.factors.black_bias,
                c.factors.white_bias,
                c.factors.uv_fit,
                c.factors.alpha_fit,
                c.factors.size_fit,
                c.factors.mean_color
            );
            assert!(
                c.factors.black_bias,
                "{mesh}: 修正原因应是 blackBias=true"
            );
            assert!(
                c.adjusted_score < 30.0,
                "{mesh}: adjustedScore {} 应落回 <30",
                c.adjusted_score
            );
        }
    }
}
