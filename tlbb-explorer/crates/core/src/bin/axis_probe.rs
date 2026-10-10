//! 逐骨/逐肢轴 A_j 的**撕边重判**（wave21）。
//!
//! wave20（`.scratch/wave20/perbone/报告.md`）判「A_j 沿子树传播」这个候选失败，
//! 用的是 frame0 世界骨位差 + 帧均位移。本班用更尖的尺重判一次：**同一个三角形
//! 面上的相邻顶点被拉开几倍**（`pose::edge_stretch`）。位移不能判撕——正常摆动
//! 本来就在搬顶点。
//!
//! # 模型（行向量约定，沿用 wave20 口径）
//!
//! 每根骨 j 有一个带符号坐标置换轴 `A_j`，轴按**分组**给定并沿整棵子树传播（组内
//! 共用一个 A）。调色板取现播放口径的增量 `P_j(t) = anchor⁻¹ · world_j(t)`
//! （= `pose::skin_palette(h, frame0_worlds, world_t)` 的输出，与轴无关，预计算），
//! 再做「父轴/自身轴不一致」的共轭：
//!
//! ```text
//! A_parent(树根) := A_j                      // 树根无父，父轴取自身
//! A_parent(j)    := A_{group(parent j)}      // 组界处 A_parent ≠ A_j
//! D_j(t) = A_parent⁻¹ · P_j(t) · A_j         // 轴是带符号置换 ⇒ 逆 = 转置
//! ```
//!
//! # ⚠ frame0 恒等不是判据，而且分组后会破
//!
//! 全身同一个 A 时 `P_j(0) = I ⇒ D_j(0) = A⁻¹·I·A = I`：**锚点恒等对任何轴选择都
//! 成立**，所以它天生不能区分谁好谁坏；以后谁拿 frame0 恒等当证据，那是在拿一个
//! 恒真的式子当判据。**只有撕边数能判。**
//!
//! 更要紧的是：**分组时组界骨 `D_j(0) = A_parent⁻¹·A_j ≠ I`**，第 0 帧不再是 bind
//! 姿态，组界那个静态偏移会直接贡献撕边。所以每条动作同时报三套数：
//! 样本帧合计（与基线同口径，判定用它）、剔除第 0 帧（看达标靠不靠那个偏移）、
//! 第 0 帧单独（看偏移多大）。
//!
//! 用法：
//! ```text
//! axis_probe --mesh=<x.mesh> --ani=<a.ani> [--ani=<b.ani> ...] --out=<报告.txt>
//!            [--json=<数字.json>] [--sample=12] [--rounds=4] [--phases=all]
//! ```
//! `--phases` 取 `global|cd5|cd6|cd8|all`。控制台是 cp936，中文只进文件，
//! stdout 只打 ASCII 进度。

use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Instant;

use tlbb_core::preview::{
    bone_count, parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose, Anim, MeshGeometry,
    Node, SkeletonHierarchy,
};

type Mat = [f32; 16];

// ─────────────────────────── 轴：48 个带符号坐标置换 ───────────────────────────

/// 一个带符号坐标置换轴。构造口径与 `stretch_probe::rsweep` 一致：**第 r 行**在第
/// `perm[r]` 列取 `signs[r]`。轴没有平移 ⇒ `A⁻¹ = Aᵀ`。
struct Axis {
    label: String,
    /// `A`
    a: Mat,
    /// `A⁻¹ = Aᵀ`
    ainv: Mat,
    det: f64,
}

fn build_axes() -> Vec<Axis> {
    let perms = [[0usize, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]];
    let mut out = Vec::with_capacity(48);
    for &p in &perms {
        for s in 0..8u8 {
            let signs = [
                if s & 1 == 0 { 1.0 } else { -1.0 },
                if s & 2 == 0 { 1.0 } else { -1.0 },
                if s & 4 == 0 { 1.0 } else { -1.0 },
            ];
            let mut a = [0f32; 16];
            for r in 0..3 {
                a[r * 4 + p[r]] = signs[r];
            }
            a[15] = 1.0;
            let ainv = transpose_axis(&a);
            let even = p == [0, 1, 2] || p == [1, 2, 0] || p == [2, 0, 1];
            out.push(Axis {
                label: format!(
                    "({},{},{})({},{},{})",
                    p[0],
                    p[1],
                    p[2],
                    if signs[0] > 0.0 { "+" } else { "-" },
                    if signs[1] > 0.0 { "+" } else { "-" },
                    if signs[2] > 0.0 { "+" } else { "-" },
                ),
                a,
                ainv,
                det: signs[0] as f64 * signs[1] as f64 * signs[2] as f64 * if even { 1.0 } else { -1.0 },
            });
        }
    }
    out
}

/// 轴求逆 = 3×3 转置（第 4 行/列不动：轴没有平移分量）。
fn transpose_axis(m: &Mat) -> Mat {
    let mut o = [0f32; 16];
    for r in 0..3 {
        for c in 0..3 {
            o[r * 4 + c] = m[c * 4 + r];
        }
    }
    o[15] = 1.0;
    o
}

/// 恒等轴（`axes[0]`）判据：元素是精确的 0/1，直接比就行。
fn is_identity(m: &Mat) -> bool {
    m[0] == 1.0
        && m[1] == 0.0
        && m[2] == 0.0
        && m[4] == 0.0
        && m[5] == 1.0
        && m[6] == 0.0
        && m[8] == 0.0
        && m[9] == 0.0
        && m[10] == 1.0
}

// ─────────────────────────── 动作：轴无关的量预计算一次 ───────────────────────────

struct Action {
    /// 短名（`idle01` / `walk` / `run`）
    label: String,
    total_frames: usize,
    step: usize,
    frames: Vec<usize>,
    /// `[样本帧序号][骨]` = `anchor⁻¹ · world_t` = `skin_palette` 的输出。
    base: Vec<Vec<Mat>>,
}

/// 一条动作在给定候选下的撕边统计。
#[derive(Clone, Copy, Debug, Default)]
struct AScore {
    /// 样本帧合计（含第 0 帧，与 `stretch_probe --rsweep` 同口径）
    s15: usize,
    s20: usize,
    mx: f64,
    /// 剔除第 0 帧
    s15_no0: usize,
    s20_no0: usize,
    mx_no0: f64,
    /// 第 0 帧单独（组界静态偏移的可见度）
    f0_15: usize,
    f0_mx: f64,
}

// ─────────────────────────── 分组 ───────────────────────────

struct Tier {
    name: String,
    /// true = 模型口径 `A_parent⁻¹·P·A_j`；false = 对照口径 `A_parent·P·A_j⁻¹`
    /// （后者就是 `stretch_probe::rsweep` 的 `R·M·Rᵀ`，用来复现基线标签）
    model_order: bool,
    group_names: Vec<String>,
    /// 骨 → 组
    group_of: Vec<usize>,
    /// 骨 → 父骨所在组（树根 = 自身组，落实 `A_parent(root) := A_j`）
    parent_group_of: Vec<usize>,
}

impl Tier {
    fn ngroups(&self) -> usize {
        self.group_names.len()
    }
}

/// 全身同一个 A 的 tier（穷举 48，不做下降）。
fn tier_whole(name: &str, model_order: bool, nbones: usize) -> Tier {
    Tier {
        name: name.to_string(),
        model_order,
        group_names: vec!["全身".to_string()],
        group_of: vec![0; nbones],
        parent_group_of: vec![0; nbones],
    }
}

/// 按组根子树分组。组根不在骨架里 → 该组空转并记警告（不硬挂、不改名）。
fn build_tier(
    h: &SkeletonHierarchy,
    name: &str,
    catch_all: &str,
    roots: &[(&str, &str)],
    warns: &mut Vec<String>,
) -> Tier {
    let n = h.bones.len();
    let mut group_of = vec![0usize; n];
    let mut group_names = vec![catch_all.to_string()];
    let mut idx_of: HashMap<&str, usize> = HashMap::new();
    for (i, b) in h.bones.iter().enumerate() {
        idx_of.insert(b.name.as_str(), i);
    }
    for (gname, root_name) in roots {
        let gid = group_names.len();
        group_names.push(gname.to_string());
        match idx_of.get(*root_name) {
            Some(&r) => {
                let mut stack = vec![r];
                while let Some(j) = stack.pop() {
                    group_of[j] = gid;
                    for &c in &h.bones[j].children {
                        stack.push(c);
                    }
                }
            }
            None => warns.push(format!("{name}：组根 `{root_name}` 不在骨架里，该组空转")),
        }
    }
    let parent_group_of = (0..n)
        .map(|j| match h.bones[j].parent {
            Some(p) => group_of[p],
            None => group_of[j],
        })
        .collect();
    Tier {
        name: name.to_string(),
        model_order: true,
        group_names,
        group_of,
        parent_group_of,
    }
}

// ─────────────────────────── 评估 ───────────────────────────

struct Ctx<'a> {
    h: &'a SkeletonHierarchy,
    nodes: &'a [Node],
    geom: &'a MeshGeometry,
    axes: &'a [Axis],
    actions: &'a [Action],
}

/// 一个候选在指定 tier 下的撕边数。**三条动作永远一起评估**：候选池是共享的，
/// 只测一条会把另外两条留成全 0 的空格子，混进排名就是假冠军（本班第一版踩过，
/// 所以这里不留「只测一条」的快路径）。
fn evaluate(ctx: &Ctx, tier: &Tier, cand: &[usize]) -> Vec<AScore> {
    let n = ctx.h.bones.len();
    // 骨 → 自身轴、父轴逆；两者都是单位阵的骨直接抄 base（省两次 4×4 乘）
    let mut self_ax: Vec<&Mat> = vec![&ctx.axes[0].a; n];
    let mut par_ax: Vec<&Mat> = vec![&ctx.axes[0].ainv; n];
    let mut pass = vec![true; n];
    for j in 0..n {
        let g = cand[tier.group_of[j]];
        let pg = cand[tier.parent_group_of[j]];
        let (a_self, a_par) = if tier.model_order {
            (&ctx.axes[g].a, &ctx.axes[pg].ainv)
        } else {
            (&ctx.axes[g].ainv, &ctx.axes[pg].a)
        };
        self_ax[j] = a_self;
        par_ax[j] = a_par;
        pass[j] = is_identity(a_self) && is_identity(a_par);
    }

    let mut pal: Vec<Mat> = vec![[0f32; 16]; n];
    let mut out = Vec::with_capacity(ctx.actions.len());
    for act in ctx.actions.iter() {
        let mut s = AScore::default();
        for (k, &fr) in act.frames.iter().enumerate() {
            let base = &act.base[k];
            for j in 0..n {
                pal[j] = if pass[j] {
                    base[j]
                } else {
                    pose::mat_mul(&pose::mat_mul(par_ax[j], &base[j]), self_ax[j])
                };
            }
            let posed = pose::posed_vertices(ctx.h, &pal, ctx.nodes, &ctx.geom.positions)
                .expect("调色板/影响表不自洽，蒙皮摆不出");
            let st = pose::edge_stretch(&ctx.geom.positions, &posed, &ctx.geom.indices);
            s.s15 += st.over15;
            s.s20 += st.over20;
            s.mx = s.mx.max(st.max_ratio);
            if k == 0 && fr == 0 {
                s.f0_15 = st.over15;
                s.f0_mx = st.max_ratio;
            } else {
                s.s15_no0 += st.over15;
                s.s20_no0 += st.over20;
                s.mx_no0 = s.mx_no0.max(st.max_ratio);
            }
        }
        out.push(s);
    }
    out
}

/// 逐帧明细（只在少数候选上打，用来写档案）。
fn frame_detail(ctx: &Ctx, tier: &Tier, cand: &[usize], ai: usize) -> Vec<(usize, usize, usize, f64)> {
    let n = ctx.h.bones.len();
    let act = &ctx.actions[ai];
    let mut rows = Vec::with_capacity(act.frames.len());
    let mut pal: Vec<Mat> = vec![[0f32; 16]; n];
    for (k, &fr) in act.frames.iter().enumerate() {
        let base = &act.base[k];
        for j in 0..n {
            let g = cand[tier.group_of[j]];
            let pg = cand[tier.parent_group_of[j]];
            let (a_self, a_par) = if tier.model_order {
                (&ctx.axes[g].a, &ctx.axes[pg].ainv)
            } else {
                (&ctx.axes[g].ainv, &ctx.axes[pg].a)
            };
            pal[j] = if is_identity(a_self) && is_identity(a_par) {
                base[j]
            } else {
                pose::mat_mul(&pose::mat_mul(a_par, &base[j]), a_self)
            };
        }
        let posed = pose::posed_vertices(ctx.h, &pal, ctx.nodes, &ctx.geom.positions).unwrap();
        let st = pose::edge_stretch(&ctx.geom.positions, &posed, &ctx.geom.indices);
        rows.push((fr, st.over15, st.over20, st.max_ratio));
    }
    rows
}

// ─────────────────────────── 撕边落在哪对骨上 ───────────────────────────

/// 每个顶点的主贡献骨（权重最大的那张影响表所属骨）；没表的下到根骨。
/// 只用来把撕边**归因**到骨对，不参与任何打分。
fn dominant_bones(ctx: &Ctx) -> Vec<usize> {
    let nv = ctx.geom.positions.len();
    let root = ctx.h.bones.iter().position(|b| b.parent.is_none()).unwrap_or(0);
    let mut best_w = vec![0f32; nv];
    let mut dom = vec![root; nv];
    let mut idx: HashMap<&str, usize> = HashMap::with_capacity(ctx.h.bones.len());
    for (i, b) in ctx.h.bones.iter().enumerate() {
        idx.insert(b.name.as_str(), i);
    }
    for nd in ctx.nodes {
        let Some(skin) = &nd.skin else { continue };
        let Some(&bi) = idx.get(nd.name.as_str()) else { continue };
        for (&v, &w) in skin.vertices.iter().zip(skin.weights.iter()) {
            let vi = v as usize;
            if vi < nv && w > best_w[vi] {
                best_w[vi] = w;
                dom[vi] = bi;
            }
        }
    }
    dom
}

/// 给定候选 + 某条动作的第 `k` 个样本帧，把超 1.5 的边按**两端主贡献骨的骨对**归堆。
/// 边的遍历与 `pose::edge_stretch` 同一条（同样跳过 < 1e-4 的退化边）。
fn tear_pairs(ctx: &Ctx, tier: &Tier, cand: &[usize], ai: usize, k: usize, dom: &[usize]) -> Vec<(String, String, usize, f64)> {
    let n = ctx.h.bones.len();
    let act = &ctx.actions[ai];
    let mut pal: Vec<Mat> = vec![[0f32; 16]; n];
    let base = &act.base[k];
    for j in 0..n {
        let g = cand[tier.group_of[j]];
        let pg = cand[tier.parent_group_of[j]];
        let (a_self, a_par) = if tier.model_order {
            (&ctx.axes[g].a, &ctx.axes[pg].ainv)
        } else {
            (&ctx.axes[g].ainv, &ctx.axes[pg].a)
        };
        pal[j] = if is_identity(a_self) && is_identity(a_par) {
            base[j]
        } else {
            pose::mat_mul(&pose::mat_mul(a_par, &base[j]), a_self)
        };
    }
    let posed = pose::posed_vertices(ctx.h, &pal, ctx.nodes, &ctx.geom.positions).unwrap();
    let dist = |a: usize, b: usize, q: &[[f32; 3]]| -> f64 {
        let d = [
            (q[a][0] - q[b][0]) as f64,
            (q[a][1] - q[b][1]) as f64,
            (q[a][2] - q[b][2]) as f64,
        ];
        (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt()
    };
    let mut acc: HashMap<(usize, usize), (usize, f64)> = HashMap::new();
    for tri in ctx.geom.indices.chunks(3) {
        if tri.len() != 3 {
            continue;
        }
        let v = [tri[0] as usize, tri[1] as usize, tri[2] as usize];
        for e in 0..3 {
            let (a, b) = (v[e], v[(e + 1) % 3]);
            let l0 = dist(a, b, &ctx.geom.positions);
            if l0 < 1e-4 {
                continue;
            }
            let r = dist(a, b, &posed) / l0;
            if r > 1.5 {
                let key = (dom[a].min(dom[b]), dom[a].max(dom[b]));
                let slot = acc.entry(key).or_insert((0, 0.0));
                slot.0 += 1;
                slot.1 = slot.1.max(r);
            }
        }
    }
    let mut intra = 0usize;
    let mut total = 0usize;
    for (&(i, j), &(c, _)) in &acc {
        total += c;
        if i == j {
            intra += c;
        }
    }
    let mut out: Vec<(String, String, usize, f64)> = acc
        .into_iter()
        .map(|((i, j), (c, mx))| (ctx.h.bones[i].name.clone(), ctx.h.bones[j].name.clone(), c, mx))
        .collect();
    out.sort_by(|a, b| b.2.cmp(&a.2).then(b.3.total_cmp(&a.3)));
    out.push(("«同骨内部»".to_string(), String::new(), intra, 0.0));
    out.push(("«超1.5合计»".to_string(), String::new(), total, 0.0));
    out
}

// ─────────────────────────── 排序键 ───────────────────────────

/// 排序键（越小越好）：先比超 1.5 边数，再比超 2 边数，最后比最大倍数。
#[derive(Clone, Copy, Debug)]
struct Rank {
    s15: u64,
    s20: u64,
    mx: f64,
}

fn rank_combined(sc: &[AScore]) -> Rank {
    let mut r = Rank { s15: 0, s20: 0, mx: 0.0 };
    for s in sc {
        r.s15 += s.s15 as u64;
        r.s20 += s.s20 as u64;
        r.mx = r.mx.max(s.mx);
    }
    r
}

fn rank_action(sc: &[AScore], i: usize) -> Rank {
    Rank { s15: sc[i].s15 as u64, s20: sc[i].s20 as u64, mx: sc[i].mx }
}

fn better(a: Rank, b: Rank) -> bool {
    match a.s15.cmp(&b.s15) {
        std::cmp::Ordering::Less => true,
        std::cmp::Ordering::Greater => false,
        std::cmp::Ordering::Equal => match a.s20.cmp(&b.s20) {
            std::cmp::Ordering::Less => true,
            std::cmp::Ordering::Greater => false,
            std::cmp::Ordering::Equal => a.mx.total_cmp(&b.mx) == std::cmp::Ordering::Less,
        },
    }
}

// ─────────────────────────── 候选池 ───────────────────────────

#[derive(Clone, Debug)]
struct Hit {
    tier: String,
    group_names: Vec<String>,
    cand: Vec<usize>,
    src: String,
    score: Vec<AScore>,
}

impl Hit {
    fn desc(&self, axes: &[Axis]) -> String {
        self.cand
            .iter()
            .enumerate()
            .map(|(g, &ax)| format!("{}={}", self.group_names[g], axes[ax].label))
            .collect::<Vec<_>>()
            .join(" ")
    }
}

/// 访问过的候选去重存下来，事后按任一动作/任一口径排名，避免「只报终点」。
struct Pool {
    map: HashMap<(String, Vec<usize>), usize>,
    hits: Vec<Hit>,
}

impl Pool {
    fn new() -> Self {
        Pool { map: HashMap::new(), hits: Vec::new() }
    }
    fn add(&mut self, tier: &Tier, cand: &[usize], src: &str, score: Vec<AScore>) {
        let key = (tier.name.clone(), cand.to_vec());
        if self.map.contains_key(&key) {
            return;
        }
        self.map.insert(key, self.hits.len());
        self.hits.push(Hit {
            tier: tier.name.clone(),
            group_names: tier.group_names.clone(),
            cand: cand.to_vec(),
            src: src.to_string(),
            score,
        });
    }
    fn best(&self, key: impl Fn(&[AScore]) -> Rank, filter: impl Fn(&Hit) -> bool) -> Option<&Hit> {
        let mut cur: Option<&Hit> = None;
        let mut ck = Rank { s15: u64::MAX, s20: u64::MAX, mx: f64::MAX };
        for x in &self.hits {
            if !filter(x) {
                continue;
            }
            let k = key(&x.score);
            if better(k, ck) {
                cur = Some(x);
                ck = k;
            }
        }
        cur
    }
}

// ─────────────────────────── 坐标下降 ───────────────────────────

/// 从 `seed` 出发最多 `rounds` 轮；每轮逐组试 48 个轴，就地取最优。
fn descend(
    ctx: &Ctx,
    tier: &Tier,
    seed: &[usize],
    rounds: usize,
    src: &str,
    key: &dyn Fn(&[AScore]) -> Rank,
    pool: &mut Pool,
    evals: &mut usize,
) -> (Vec<usize>, Vec<AScore>) {
    let mut cur = seed.to_vec();
    let mut cur_score = evaluate(ctx, tier, &cur);
    let mut cur_key = key(&cur_score);
    *evals += 1;
    pool.add(tier, &cur, src, cur_score.clone());
    for _ in 0..rounds {
        let mut moved = false;
        for g in 0..tier.ngroups() {
            for ax in 0..ctx.axes.len() {
                if ax == cur[g] {
                    continue;
                }
                let mut trial = cur.clone();
                trial[g] = ax;
                let sc = evaluate(ctx, tier, &trial);
                *evals += 1;
                pool.add(tier, &trial, src, sc.clone());
                let k = key(&sc);
                if better(k, cur_key) {
                    cur = trial;
                    cur_score = sc;
                    cur_key = k;
                    moved = true;
                }
            }
        }
        if !moved {
            break;
        }
    }
    (cur, cur_score)
}

// ─────────────────────────── CLI 与出表 ───────────────────────────

fn arg(argv: &[String], name: &str) -> Option<PathBuf> {
    let want = format!("--{name}=");
    argv.iter()
        .skip(1)
        .find_map(|a| a.strip_prefix(&want))
        .map(|s| PathBuf::from(s.trim_matches('"')))
}

fn arg_str(argv: &[String], name: &str) -> Option<String> {
    let want = format!("--{name}=");
    argv.iter().skip(1).find_map(|a| a.strip_prefix(&want)).map(|s| s.to_string())
}

fn arg_all<'a>(argv: &'a [String], name: &str) -> Vec<PathBuf> {
    let want = format!("--{name}=");
    argv.iter()
        .skip(1)
        .filter_map(|a| a.strip_prefix(&want))
        .map(|s| PathBuf::from(s.trim_matches('"')))
        .collect()
}

/// `w1351_..._idle01` 去掉与 mesh 共有的前缀段，留短名。
fn short_name(mesh_stem: &str, ani_stem: &str) -> String {
    let m: Vec<&str> = mesh_stem.split('_').collect();
    let a: Vec<&str> = ani_stem.split('_').collect();
    let mut common = 0;
    while common < m.len() && common < a.len() && m[common] == a[common] {
        common += 1;
    }
    if common >= a.len() {
        ani_stem.to_string()
    } else {
        a[common..].join("_")
    }
}

fn fmt2(v: f64) -> String {
    format!("{v:.2}")
}

/// 一行三条动作的 over15/over20/max。
fn score_cells(sc: &[AScore]) -> String {
    sc.iter()
        .map(|s| format!("{}/{}/{}", s.s15, s.s20, fmt2(s.mx)))
        .collect::<Vec<_>>()
        .join(" | ")
}

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let mesh = arg(&argv, "mesh").expect("要带 --mesh=<路径>");
    let anis = arg_all(&argv, "ani");
    if anis.is_empty() {
        panic!("要带至少一个 --ani=<路径>");
    }
    let out_path = arg(&argv, "out").unwrap_or_else(|| PathBuf::from("axis_probe.txt"));
    let json_path = arg(&argv, "json");
    let sample: usize = arg_str(&argv, "sample").and_then(|s| s.parse().ok()).unwrap_or(12);
    let rounds: usize = arg_str(&argv, "rounds").and_then(|s| s.parse().ok()).unwrap_or(4);
    let phases = arg_str(&argv, "phases").unwrap_or_else(|| "all".to_string());
    let want = |p: &str| phases.split(',').any(|x| x.trim() == p) || phases.trim() == "all";

    let raw_mesh = std::fs::read(&mesh).expect("读不到 mesh");
    let layout = parse_mesh(&raw_mesh).expect("mesh 解析失败");
    let h = parse_hierarchy(&raw_mesh).expect("骨架解不出");
    let nodes = parse_nodes(&raw_mesh);
    let g = &layout.geometry;
    let mesh_stem = mesh.file_stem().unwrap().to_string_lossy().to_string();

    let mut rep = String::new();
    rep.push_str("# axis_probe · 逐骨/逐肢轴按撕边重判（wave21）\n\n");
    rep.push_str(&format!(
        "命令：`{}`\n\nmesh `{}` · 顶点 {} / 三角面 {}（每帧参与量尺的边 2,538 条量级）/ 骨 {}（声明 {}）/ 节点记录 {} 条\n\n",
        argv.join(" "),
        mesh_stem,
        g.positions.len(),
        g.indices.len() / 3,
        h.bones.len(),
        bone_count(&raw_mesh).unwrap_or(0),
        nodes.len()
    ));

    // ── 动作 ──
    let mut actions: Vec<Action> = Vec::new();
    rep.push_str("## 0) 取样口径\n\n");
    for p in &anis {
        let raw = std::fs::read(p).expect("读不到 ani");
        let a: Anim = parse_ani(&raw).expect("ani 解析失败");
        let step = (a.frames / sample).max(1);
        let frames: Vec<usize> = (0..a.frames).step_by(step).collect();
        let anchor = pose::pose_frame(&h, &a, 0);
        let mut base = Vec::with_capacity(frames.len());
        for &f in &frames {
            let world = pose::pose_frame(&h, &a, f);
            base.push(pose::skin_palette(&h, &anchor, &world).expect("调色板解不出"));
        }
        let label = short_name(&mesh_stem, &p.file_stem().unwrap().to_string_lossy());
        rep.push_str(&format!(
            "- **{label}** `{}`：{} 帧，步长 `max(1,{}/{})` = {step} ⇒ 取样 {} 帧：{}\n",
            p.file_name().unwrap().to_string_lossy(),
            a.frames,
            a.frames,
            sample,
            frames.len(),
            frames.iter().map(|f| f.to_string()).collect::<Vec<_>>().join(",")
        ));
        actions.push(Action { label, total_frames: a.frames, step, frames, base });
    }
    rep.push_str(&format!(
        "\n判定用「样本帧合计（含第 0 帧）」，与 `stretch_probe --rsweep` 同口径。\n\n## 0b) 骨清单（下标 / 父 / 子）\n\n```\n"
    ));
    for (i, b) in h.bones.iter().enumerate() {
        rep.push_str(&format!(
            "{i:2} {:<30} parent {:>4} children {:?}\n",
            b.name,
            b.parent.map(|p| p.to_string()).unwrap_or_else(|| "-".to_string()),
            b.children
        ));
    }
    rep.push_str("```\n");

    // 带权重表的骨：分组只在「组根本身带权重」时才会落到皮肤上，这张表解释
    // 为什么第 0 帧在分组候选下仍然恒等（组界偏移没被任何蒙皮顶点吃到）。
    rep.push_str("\n带影响顶点表的骨（`parse_nodes` 的 96B 记录 + 稀疏权重表）：\n\n```\n");
    let mut name_idx: HashMap<&str, usize> = HashMap::with_capacity(h.bones.len());
    for (i, b) in h.bones.iter().enumerate() {
        name_idx.insert(b.name.as_str(), i);
    }
    let mut covered = vec![0usize; h.bones.len()];
    for nd in &nodes {
        let Some(sk) = &nd.skin else { continue };
        if let Some(&i) = name_idx.get(nd.name.as_str()) {
            covered[i] = sk.vertices.len();
        }
    }
    for (i, b) in h.bones.iter().enumerate() {
        if covered[i] > 0 {
            rep.push_str(&format!("{i:2} {:<30} {} 顶点\n", b.name, covered[i]));
        }
    }
    rep.push_str(&format!(
        "带表 {} 根 / 无表 {} 根（无表的骨没有权重，轴换得再花也碰不到皮肤）\n```",
        covered.iter().filter(|&&c| c > 0).count(),
        covered.iter().filter(|&&c| c == 0).count()
    ));

    let axes = build_axes();
    assert_eq!(axes.len(), 48, "轴表必须是 48 个");
    assert_eq!(axes[0].label, "(0,1,2)(+,+,+)", "axes[0] 必须是恒等");
    let ctx = Ctx { h: &h, nodes: &nodes, geom: g, axes: &axes, actions: &actions };
    let mut pool = Pool::new();
    let mut evals = 0usize;
    let mut warns: Vec<String> = Vec::new();
    let t0 = Instant::now();

    // ── T1 全身同一个 A：穷举 48，两个共轭方向都跑 ──
    let t1 = tier_whole("T1 全身一个 A", true, h.bones.len());
    let t1b = tier_whole("T1b 全身一个 A（对一口径）", false, h.bones.len());
    for tier in [&t1, &t1b] {
        for ax in 0..48 {
            let cand = vec![ax];
            let sc = evaluate(&ctx, tier, &cand);
            evals += 1;
            pool.add(tier, &cand, "穷举48", sc);
        }
    }
    println!("T1 evals={evals} {:?}", t0.elapsed());

    // ── 1) 基线复现 ──
    rep.push_str("\n## 1) 基线复现\n\n");
    rep.push_str(
        "外部给定（必须复现，复现不了就是实现有问题）：恒等轴 idle01 在 14 帧取样下 over15 合计 = **2,959**；\n\
         全局最好 `(2,1,0)(+,-,+)` = **810**（max 4.07）。口径来自 `stretch_probe --rsweep`：\n\
         取样 `(0..frames).step_by(max(1,frames/12))`（含第 0 帧），共轭写成 `R·M·Rᵀ`。\n\n",
    );
    for tier in [&t1, &t1b] {
        let id = pool.hits.iter().find(|x| x.tier == tier.name && x.cand == vec![0usize]).unwrap();
        rep.push_str(&format!(
            "- {} **恒等** ⇒ {} ⇒ 恒等复现 **{}**\n",
            tier.name,
            id.score
                .iter()
                .enumerate()
                .map(|(i, s)| format!("{} over15 {} / over20 {} / max {}", actions[i].label, s.s15, s.s20, fmt2(s.mx)))
                .collect::<Vec<_>>()
                .join(" · "),
            if id.score[0].s15 == 2959 { "PASS" } else { "FAIL（与 2,959 不符）" }
        ));
    }
    for tier in [&t1, &t1b] {
        let mut rows: Vec<&Hit> = pool.hits.iter().filter(|x| x.tier == tier.name).collect();
        rows.sort_by_key(|x| (x.score[0].s15, x.score[0].s20));
        rep.push_str(&format!("\n{} · 按 idle01 over15 排前 6：\n\n", tier.name));
        rep.push_str("| A | det | idle01 15/20/max | walk 15/20/max | run 15/20/max |\n|---|---|---|---|---|\n");
        for x in rows.iter().take(6) {
            rep.push_str(&format!(
                "| {} | {:+.0} | {} |\n",
                x.desc(&axes).replace("全身=", ""),
                axes[x.cand[0]].det,
                score_cells(&x.score)
            ));
        }
        let named = rows.iter().find(|x| axes[x.cand[0]].label == "(2,1,0)(+,-,+)");
        if let Some(x) = named {
            rep.push_str(&format!(
                "\n标签 `(2,1,0)(+,-,+)` 在本口径下 idle01 = {} ⇒ **{}**\n",
                x.score[0].s15,
                if x.score[0].s15 == 810 { "PASS" } else { "不是 810（见下方转置对号）" }
            ));
        }
        match rows.iter().find(|x| x.score[0].s15 == 810) {
            Some(x) => rep.push_str(&format!(
                "本口径下能取到 idle01 = 810 的标签：**{}**（max {}）。48 集合对转置封闭，\n\
                 所以 810 这个数在两个口径里都存在，只是标签互为转置。\n",
                x.desc(&axes).replace("全身=", ""),
                fmt2(x.score[0].mx)
            )),
            None => rep.push_str(&format!(
                "本口径下**取不到** idle01 = 810；最好 {}（前一名 {}）。基线未复现，后面的数不能用。\n",
                rows[0].score[0].s15,
                rows[0].desc(&axes).replace("全身=", "")
            )),
        }
    }

    // ── 全局 48 全表（模型口径）──
    rep.push_str("\n## 1b) 全局 48 全表（模型口径 `A⁻¹·P·A`，按 Σover15 排）\n\n");
    {
        let mut rows: Vec<&Hit> = pool.hits.iter().filter(|x| x.tier == t1.name).collect();
        rows.sort_by_key(|x| rank_combined(&x.score).s15);
        rep.push_str("| # | A | det | idle01 | walk | run | Σ15 |\n|---|---|---|---|---|---|---:|\n");
        for (r, x) in rows.iter().enumerate() {
            rep.push_str(&format!(
                "| {} | {} | {:+.0} | {} | {} | {} | {} |\n",
                r + 1,
                x.desc(&axes).replace("全身=", ""),
                axes[x.cand[0]].det,
                x.score[0].s15,
                x.score[1].s15,
                x.score[2].s15,
                rank_combined(&x.score).s15
            ));
        }
    }

    // ── 2) 分组坐标下降 ──
    let mut tiers: Vec<Tier> = Vec::new();
    if want("cd5") {
        tiers.push(build_tier(
            &h,
            "T5 五大肢",
            "脊柱",
            &[("左臂", "bip01_l_clavicle"), ("右臂", "bip01_r_clavicle"), ("左腿", "bip01_l_thigh"), ("右腿", "bip01_r_thigh")],
            &mut warns,
        ));
    }
    if want("cd6") {
        tiers.push(build_tier(
            &h,
            "T6 大肢+头颈",
            "脊柱",
            &[("头颈", "bip01_neck"), ("左臂", "bip01_l_clavicle"), ("右臂", "bip01_r_clavicle"), ("左腿", "bip01_l_thigh"), ("右腿", "bip01_r_thigh")],
            &mut warns,
        ));
    }
    if want("cd8") {
        tiers.push(build_tier(
            &h,
            "T8 大肢+头颈+双手",
            "脊柱",
            &[("头颈", "bip01_neck"), ("左臂", "bip01_l_clavicle"), ("右臂", "bip01_r_clavicle"), ("左腿", "bip01_l_thigh"), ("右腿", "bip01_r_thigh"), ("左手", "bip01_l_hand"), ("右手", "bip01_r_hand")],
            &mut warns,
        ));
    }
    rep.push_str("\n## 2) 分组坐标下降\n\n");
    if tiers.is_empty() {
        rep.push_str("（`--phases=global`：本轮没跑分组下降）\n");
    } else {
        let gcomb = pool.best(rank_combined, |x| x.tier == t1.name).unwrap().cand[0];
        let gidle = pool.best(|s| rank_action(s, 0), |x| x.tier == t1.name).unwrap().cand[0];
        rep.push_str(&format!(
            "种子（3 个，全部 tier 共用）：恒等 `(0,1,2)(+,+,+)` / 全局跨动作最优 `{}` / 全局 idle01 最优 `{}`。\n\
             预算：每 tier = 3 起点 ×（跨动作 1 目标 + {} 个单动作目标）× 最多 {rounds} 轮 × 组数 × 48。\n\n",
            axes[gcomb].label,
            axes[gidle].label,
            actions.len()
        ));
        for tier in &tiers {
            rep.push_str(&format!(
                "\n### {}（{} 组：{}）\n\n",
                tier.name,
                tier.ngroups(),
                tier.group_names
                    .iter()
                    .enumerate()
                    .map(|(gi, n)| format!("{n} {}根", tier.group_of.iter().filter(|&&x| x == gi).count()))
                    .collect::<Vec<_>>()
                    .join(" / ")
            ));
            let seeds: Vec<(&str, usize)> = vec![("恒等", 0), ("全局最优", gcomb), ("idle01最优", gidle)];
            for (sname, ax) in &seeds {
                let seed = vec![*ax; tier.ngroups()];
                let (c, sc) = descend(
                    &ctx,
                    tier,
                    &seed,
                    rounds,
                    &format!("{sname}·跨动作"),
                    &rank_combined,
                    &mut pool,
                    &mut evals,
                );
                rep.push_str(&format!(
                    "- 起点 {sname} → 跨动作最优 {} ⇒ Σ15 {} · {} · max {} / 剔0帧 max {}\n",
                    c.iter()
                        .enumerate()
                        .map(|(g, &a)| format!("{}={}", tier.group_names[g], axes[a].label))
                        .collect::<Vec<_>>()
                        .join(" "),
                    rank_combined(&sc).s15,
                    sc.iter()
                        .enumerate()
                        .map(|(i, s)| format!("{} {}", actions[i].label, s.s15))
                        .collect::<Vec<_>>()
                        .join(" "),
                    fmt2(rank_combined(&sc).mx),
                    fmt2(sc.iter().map(|s| s.mx_no0).fold(0.0f64, f64::max)),
                ));
                println!("{} {sname} combined done evals={evals} {:?}", tier.name, t0.elapsed());
            }
            for (ai, act) in actions.iter().enumerate() {
                let key = move |s: &[AScore]| rank_action(s, ai);
                for (sname, ax) in &seeds {
                    let seed = vec![*ax; tier.ngroups()];
                    let (_, sc) = descend(
                        &ctx,
                        tier,
                        &seed,
                        rounds,
                        &format!("{sname}·{}", act.label),
                        &key,
                        &mut pool,
                        &mut evals,
                    );
                    let best = pool.best(move |s| rank_action(s, ai), |x| x.tier == tier.name).unwrap();
                    rep.push_str(&format!(
                        "- 起点 {sname} → 单目标 {}：本终点 {} · 池内该动作最好 {} ⇒ over15 {} / over20 {} / max {}（剔0帧 {} / {}）\n",
                        act.label,
                        fmt2(sc[ai].mx),
                        best.desc(&axes),
                        best.score[ai].s15,
                        best.score[ai].s20,
                        fmt2(best.score[ai].mx),
                        best.score[ai].s15_no0,
                        fmt2(best.score[ai].mx_no0),
                    ));
                    println!("{} {} done evals={evals} {:?}", tier.name, act.label, t0.elapsed());
                }
            }
        }
    }

    // ── 3) 每条动作的前 5 名（全池）──
    rep.push_str("\n## 3) 每条动作前 5 名（全池：穷举 + 所有下降访问过的候选）\n\n");
    rep.push_str("数 = 该动作样本帧合计（含第 0 帧）over15 / over20 / max_ratio。\n\n");
    for (ai, act) in actions.iter().enumerate() {
        let mut rows: Vec<&Hit> = pool.hits.iter().collect();
        rows.sort_by_key(|x| (rank_action(&x.score, ai).s15, rank_action(&x.score, ai).s20));
        rep.push_str(&format!(
            "\n### {}（共 {} 帧，步长 max(1,{}/{}) = {}，取样 {} 帧）\n\n",
            act.label,
            act.total_frames,
            act.total_frames,
            sample,
            act.step,
            act.frames.len()
        ));
        rep.push_str("| # | tier | 候选 | 来源 | over15 | over20 | max | 剔0帧 over15 | 剔0帧 max | 第0帧 over15 |\n|---|---|---|---|---:|---:|---:|---:|---:|---:|\n");
        for (r, x) in rows.iter().take(5).enumerate() {
            let s = x.score[ai];
            rep.push_str(&format!(
                "| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |\n",
                r + 1,
                x.tier,
                x.desc(&axes),
                x.src,
                s.s15,
                s.s20,
                fmt2(s.mx),
                s.s15_no0,
                fmt2(s.mx_no0),
                s.f0_15
            ));
        }
        if let Some(x) = pool.hits.iter().find(|x| x.tier == t1.name && x.cand == vec![0usize]) {
            let n_better = pool.hits.iter().filter(|y| better(rank_action(&y.score, ai), rank_action(&x.score, ai))).count();
            rep.push_str(&format!(
                "\n恒等基线 {label}：over15 {s15} / over20 {s20} / max {mx}（池内 {n} 个候选按本动作比它好）\n",
                label = act.label,
                s15 = x.score[ai].s15,
                s20 = x.score[ai].s20,
                mx = fmt2(x.score[ai].mx),
                n = n_better
            ));
        }
    }

    // ── 4) 跨动作一致候选 ──
    rep.push_str("\n## 4) 跨动作一致候选（同一个候选同时打三条）\n\n");
    rep.push_str("| # | tier | 候选 |");
    for a in &actions {
        rep.push_str(&format!(" {} over15/max |", a.label));
    }
    rep.push_str(" Σ15 | 剔0帧 Σ15 | 剔0帧 max |\n|---|---|---|");
    for _ in &actions {
        rep.push_str("---|");
    }
    rep.push_str("---|---|---|\n");
    let mut comb: Vec<&Hit> = pool.hits.iter().collect();
    comb.sort_by_key(|x| (rank_combined(&x.score).s15, rank_combined(&x.score).s20));
    for (r, x) in comb.iter().take(12).enumerate() {
        rep.push_str(&format!(
            "| {} | {} | {} | {} | {} | {} | {} |\n",
            r + 1,
            x.tier,
            x.desc(&axes),
            x.score.iter().map(|s| format!("{} / {}", s.s15, fmt2(s.mx))).collect::<Vec<_>>().join(" | "),
            rank_combined(&x.score).s15,
            x.score.iter().map(|s| s.s15_no0 as u64).sum::<u64>(),
            fmt2(x.score.iter().map(|s| s.mx_no0).fold(0.0f64, f64::max)),
        ));
    }

    // ── 5) 判定线 ──
    rep.push_str("\n## 5) 判定线（写死，别自欺）\n\n");
    let mut glob_best: Vec<usize> = Vec::new();
    for ai in 0..actions.len() {
        let b = pool.best(|s| rank_action(s, ai), |x| x.tier == t1.name).unwrap();
        glob_best.push(b.score[ai].s15);
        rep.push_str(&format!(
            "- 全局 R 最好 {}：over15 {}（标签 {}）⇒ 1/3 门槛 {}\n",
            actions[ai].label,
            b.score[ai].s15,
            b.desc(&axes).replace("全身=", ""),
            b.score[ai].s15 / 3
        ));
    }
    rep.push_str(
        "\n🟢 需要：存在一个候选，让三条动作 over15 合计都 ≤ 各自门槛，且三条 max_ratio 都 < 2.0。\n\
         🟡 只有个别动作达标。🔴 最优仍 max_ratio ≥ 2.0，或冠军逐动作漂移。\n\n",
    );
    // 全池 max_ratio 的下限（不许拿「前 5 名里的最小」冒充「全池最小」）
    rep.push_str("全池 max_ratio 下限（这才是「max 能不能压到 2.0 以下」的答案）：\n");
    for (ai, act) in actions.iter().enumerate() {
        let mut bmn: Option<(f64, &Hit)> = None;
        let mut bok: Option<(usize, &Hit)> = None;
        for x in &pool.hits {
            if x.tier == t1b.name {
                continue;
            }
            let s = x.score[ai];
            if bmn.map(|(m, _)| s.mx < m).unwrap_or(true) {
                bmn = Some((s.mx, x));
            }
            if bok.map(|(m, _)| s.s15 < m).unwrap_or(true) {
                bok = Some((s.s15, x));
            }
        }
        if let (Some((m, x)), Some((o, _))) = (bmn, bok) {
            rep.push_str(&format!(
                "- {}：全池 over15 最低 {o}；全池 max_ratio 最低 {}（来自 {} · {}）\n",
                act.label,
                fmt2(m),
                x.tier,
                x.desc(&axes)
            ));
        }
    }
    let thr = |i: usize| (glob_best[i] as f64 / 3.0).max(1.0);
    let gate = |x: &Hit, no0: bool| -> Option<f64> {
        if x.score.len() != actions.len() {
            return None;
        }
        let mut m = 0f64;
        for (i, s) in x.score.iter().enumerate() {
            let (c, mx) = if no0 { (s.s15_no0, s.mx_no0) } else { (s.s15, s.mx) };
            m = m.max(c as f64 / thr(i)).max(mx / 2.0);
        }
        Some(m)
    };
    let mut gated: Vec<(f64, &Hit)> = pool.hits.iter().filter_map(|x| gate(x, false).map(|m| (m, x))).collect();
    gated.sort_by(|a, b| a.0.total_cmp(&b.0));
    rep.push_str(&format!(
        "gate = max( over15/门槛, max_ratio/2.0 )，≤ 1 即过线（含第 0 帧口径）。\n\
         池内最接近达标：{} —— {}\n\n",
        if gated.first().map(|(m, _)| *m <= 1.0).unwrap_or(false) { "🟢 有候选过线" } else { "🔴 无候选过线" },
        gated
            .iter()
            .take(6)
            .map(|(m, x)| format!("{m:.3} {} · {}", x.tier, x.desc(&axes)))
            .collect::<Vec<_>>()
            .join("\n  ")
    ));
    for (m, x) in gated.iter().take(6) {
        rep.push_str(&format!(
            "  gate={m:.3} · {}\n",
            x.score
                .iter()
                .enumerate()
                .map(|(i, s)| format!(
                    "{} over15 {}（门槛的 {:.2}×）/ max {}（剔0帧 {}）",
                    actions[i].label,
                    s.s15,
                    s.s15 as f64 / thr(i),
                    fmt2(s.mx),
                    fmt2(s.mx_no0)
                ))
                .collect::<Vec<_>>()
                .join(" · ")
        ));
    }
    // 剔第 0帧口径的 gate（检查达标靠不靠组界静态偏移）
    let mut gated0: Vec<(f64, &Hit)> = pool.hits.iter().filter_map(|x| gate(x, true).map(|m| (m, x))).collect();
    gated0.sort_by(|a, b| a.0.total_cmp(&b.0));
    if let Some((m, x)) = gated0.first() {
        rep.push_str(&format!(
            "\n剔除第 0 帧后最接近达标：gate {m:.3} · {} · {}\n",
            x.tier,
            x.desc(&axes)
        ));
    }
    // 冠军漂移检查
    rep.push_str("\n冠军是否逐动作漂移：\n");
    for ai in 0..actions.len() {
        let b = pool
            .best(|s| rank_action(s, ai), |x| x.tier != t1b.name && x.score.iter().any(|s| s.mx > 0.0))
            .unwrap();
        rep.push_str(&format!(
            "- {} 单动作最好（全池，含分组）：{} · {} ⇒ over15 {}\n",
            actions[ai].label,
            b.tier,
            b.desc(&axes),
            b.score[ai].s15
        ));
    }
    let cross = pool
        .best(rank_combined, |x| x.tier != t1b.name && x.score.iter().any(|s| s.mx > 0.0))
        .unwrap();
    rep.push_str(&format!(
        "- 跨动作一致最好：{} · {} ⇒ Σ15 {}（{}）\n",
        cross.tier,
        cross.desc(&axes),
        rank_combined(&cross.score).s15,
        cross
            .score
            .iter()
            .enumerate()
            .map(|(i, s)| format!("{} {}/max {}", actions[i].label, s.s15, fmt2(s.mx)))
            .collect::<Vec<_>>()
            .join(" · ")
    ));

    // ── 6) 逐帧明细 ──
    rep.push_str("\n## 6) 逐帧明细（每帧 over15 / over20 / max_ratio）\n\n");
    // 按 hit 的 tier 名找回那个 tier 的分组表，避免「组数刚好相同」认错分组
    let all_tiers: Vec<&Tier> = vec![&t1, &t1b].into_iter().chain(tiers.iter()).collect();
    let tier_of = |name: &str| -> &Tier {
        all_tiers.iter().copied().find(|t| t.name == name).unwrap_or(&t1)
    };
    for (ai, act) in actions.iter().enumerate() {
        let id_hit = pool.hits.iter().find(|x| x.tier == t1.name && x.cand == vec![0usize]).unwrap();
        let glob_hit = pool.best(|s| rank_action(s, ai), |x| x.tier == t1.name).unwrap();
        let picks: Vec<(&str, &Hit)> = vec![("恒等", id_hit), ("全局最好", glob_hit), ("跨动作一致最好", cross)];
        rep.push_str(&format!(
            "\n### {}（共 {} 帧，取样 {} 帧；格子写 `超1.5·超2/最大`）\n\n",
            act.label, act.total_frames, act.frames.len()
        ));
        let mut head = String::from("| 候选 |");
        for f in &act.frames {
            head.push_str(&format!(" {f} |"));
        }
        rep.push_str(&head);
        rep.push_str("\n|---|");
        for _ in &act.frames {
            rep.push_str("---|");
        }
        rep.push_str("\n");
        for (name, hit) in picks {
            let tier = tier_of(&hit.tier);
            let rows = frame_detail(&ctx, tier, &hit.cand, ai);
            rep.push_str(&format!("| {name} · {} |", hit.desc(&axes)));
            for (_, o15, o20, mx) in rows {
                rep.push_str(&format!(" {}·{}/{} |", o15, o20, fmt2(mx)));
            }
            rep.push_str("\n");
        }
    }

    // ── 7) 残差落在哪对骨上 ──
    rep.push_str("\n## 7) 残差落在哪对骨上\n\n");
    rep.push_str(
        "取各自动作里 over15 最多的那个样本帧，把超 1.5 的边按**两端主贡献骨**（权重最大的骨）归堆。\n\
         用途：看残差是「某个组界的一对骨」还是「全身均匀」——前者说明还有局部轴可救，\n\
         后者说明错的不是轴。尺与 `edge_stretch` 同一条遍历。\n\n",
    );
    let dom = dominant_bones(&ctx);
    let id_hit = pool.hits.iter().find(|x| x.tier == t1.name && x.cand == vec![0usize]).unwrap();
    for (ai, act) in actions.iter().enumerate() {
        for (tag, hit) in [("恒等", id_hit), ("跨动作一致最好", cross)] {
            let tier = tier_of(&hit.tier);
            let det = frame_detail(&ctx, tier, &hit.cand, ai);
            let mut wk = 0usize;
            for (kk, r) in det.iter().enumerate() {
                if r.1 > det[wk].1 {
                    wk = kk;
                }
            }
            let (fr, o15, o20, mx) = det[wk];
            rep.push_str(&format!(
                "### {} · {tag} · 第 {fr} 帧（over15 {o15} / over20 {o20} / max {m}）\n\n",
                act.label,
                m = fmt2(mx)
            ));
            rep.push_str("| 骨对 | 边数 | 最大倍数 |\n|---|---:|---:|\n");
            let mut rows = tear_pairs(&ctx, tier, &hit.cand, ai, wk, &dom);
            let total = rows.pop().map(|r| r.2).unwrap_or(0);
            let intra = rows.pop().map(|r| r.2).unwrap_or(0);
            for (a, b, c, m) in rows.into_iter().take(8) {
                rep.push_str(&format!("| {a} ↔ {b} | {c} | {} |\n", fmt2(m)));
            }
            rep.push_str(&format!(
                "\n同骨内部（两端主贡献骨是同一根 ⇒ 正交轴**改不动**，只能是缩放/权重补根造成的）：\
                 {intra}/{total} = {:.0}%\n\n",
                100.0 * intra as f64 / (total.max(1) as f64)
            ));
        }
    }

    if !warns.is_empty() {
        rep.push_str("\n## 警告\n\n");
        for w in &warns {
            rep.push_str(&format!("- {w}\n"));
        }
    }
    rep.push_str(&format!(
        "\n---\n评估次数（含重复）{evals} · 去重候选 {} · 耗时 {:?} · 轴 48 · phases={phases} · rounds={rounds} · sample={sample}\n",
        pool.hits.len(),
        t0.elapsed()
    ));
    std::fs::write(&out_path, rep.as_bytes()).expect("写不出报告");

    if let Some(jp) = json_path {
        let mut j = String::from("{\n  \"evals\": ");
        j.push_str(&format!("{evals},\n  \"hits\": {},\n  \"top\": [\n", pool.hits.len()));
        let mut rows: Vec<&Hit> = pool.hits.iter().collect();
        rows.sort_by_key(|x| rank_combined(&x.score).s15);
        for (r, x) in rows.iter().take(40).enumerate() {
            j.push_str(&format!(
                "    {{\"tier\": \"{}\", \"cand\": {:?}, \"axes\": [{}], \"score\": [{}]}}{}",
                x.tier,
                x.cand,
                x.cand.iter().map(|&a| format!("\"{}\"", axes[a].label)).collect::<Vec<_>>().join(","),
                x.score
                    .iter()
                    .map(|s| format!("{{\"s15\":{},\"s20\":{},\"mx\":{:.4},\"s15_no0\":{},\"mx_no0\":{:.4},\"f0_15\":{}}}", s.s15, s.s20, s.mx, s.s15_no0, s.mx_no0, s.f0_15))
                    .collect::<Vec<_>>()
                    .join(","),
                if r + 1 == rows.len().min(40) { "" } else { "," }
            ));
            j.push('\n');
        }
        j.push_str("  ]\n}\n");
        std::fs::write(&jp, j.as_bytes()).expect("写不出 json");
    }
    println!("WROTE {}", out_path.display());
}
