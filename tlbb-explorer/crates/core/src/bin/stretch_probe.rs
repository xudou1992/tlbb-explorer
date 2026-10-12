//! 边长拉伸探针：用 **app 自己的蒙皮路径**（`pose::skin_palette` +
//! `posed_vertices`）逐帧量三角形边长相对 bind 的倍数，一次比几种播放锚。
//!
//! 与 `.scratch/glb_ext/view.html` 里 three.js 侧的 `__stretch` 是同一把尺：
//! 顶点位移判不了撕不撕（正常摆动也会把顶点搬走），**同一个面上的相邻顶点被
//! 拉开距离**才是撕。两边数字对上，才能说「导出与 app 内一致」。
//!
//! 用法：
//! ```text
//! stretch_probe --mesh=<x.mesh> --ani=<x_idle01.ani> [--step=5]
//! ```

use std::path::PathBuf;

use tlbb_core::preview::{
    bone_count, parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose,
    rebuild_bind_positions, rest_poses,
};

fn arg(argv: &[String], name: &str) -> Option<PathBuf> {
    let want = format!("--{name}=");
    argv.iter()
        .skip(1)
        .find_map(|a| a.strip_prefix(&want))
        .map(|s| PathBuf::from(s.trim_matches('"')))
}

/// 一份蒙皮结果相对 bind 的边长倍数分布（尺在 `pose::edge_stretch`，与闸门同一份）。
fn stretch(bind: &[[f32; 3]], posed: &[[f32; 3]], indices: &[u16]) -> (usize, usize, f64) {
    let s = pose::edge_stretch(bind, posed, indices);
    (s.over15, s.over20, s.max_ratio)
}

/// 48 个全局带符号轴置换，逐个共轭播放调色板，按**撕边数**排名。
///
/// 为什么这条值得再扫一遍：10-06 那次扫 48 用的是位移类指标（帧均位移、
/// 变形重心贴骨位），全局刚体运动不参与，所以「谁最好」在几个候选之间来回漂。
/// 边长倍数对全局刚体不变、只对**骨与骨之间的相对错位**敏感，是更尖的尺。
///
/// 口径：行向量下换基 `x = y·R` ⇒ 网格坐标里的骨变换 = `R·M·R⁻¹`（R 正交，
/// `R⁻¹ = Rᵀ`）。调色板是逐骨相对第 0 帧的增量，所以共轭的是增量。
fn rsweep(
    h: &tlbb_core::preview::SkeletonHierarchy,
    a: &tlbb_core::preview::Anim,
    nodes: &[tlbb_core::preview::Node],
    pos: &[[f32; 3]],
    idx: &[u16],
    anchor: &[[f32; 16]],
) {
    let perms = [[0usize, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]];
    let mut results: Vec<(String, usize, usize, f64)> = Vec::new();
    let frames: Vec<usize> = (0..a.frames).step_by(3.max(a.frames / 12)).collect();
    for &p in &perms {
        for s in 0..8u8 {
            let signs = [
                if s & 1 == 0 { 1.0 } else { -1.0 },
                if s & 2 == 0 { 1.0 } else { -1.0 },
                if s & 4 == 0 { 1.0 } else { -1.0 },
            ];
            let mut rr = [0f32; 16];
            for r in 0..3 {
                rr[r * 4 + p[r]] = signs[r];
            }
            rr[15] = 1.0;
            let mut rt = [0f32; 16];
            for r in 0..3 {
                for c in 0..3 {
                    rt[r * 4 + c] = rr[c * 4 + r];
                }
            }
            rt[15] = 1.0;
            let (mut sum15, mut sum20) = (0usize, 0usize);
            let mut worst = 0f64;
            for &f in &frames {
                let world = pose::pose_frame(h, a, f);
                let Some(d) = pose::skin_palette(h, anchor, &world) else { continue };
                let pal: Vec<[f32; 16]> = d
                    .iter()
                    .map(|m| pose::mat_mul(&pose::mat_mul(&rr, m), &rt))
                    .collect();
                let Some(posed) = pose::posed_vertices(h, &pal, nodes, pos) else { continue };
                let s = pose::edge_stretch(pos, &posed, idx);
                sum15 += s.over15;
                sum20 += s.over20;
                worst = worst.max(s.max_ratio);
            }
            let det = signs[0] * signs[1] * signs[2] * if p == [0, 1, 2] || p == [1, 2, 0] || p == [2, 0, 1] { 1.0 } else { -1.0 };
            results.push((
                format!("({},{},{})({},{},{}) det{:+.0}", p[0], p[1], p[2],
                    if signs[0] > 0.0 { "+" } else { "-" },
                    if signs[1] > 0.0 { "+" } else { "-" },
                    if signs[2] > 0.0 { "+" } else { "-" }, det),
                sum15,
                sum20,
                worst,
            ));
        }
    }
    results.sort_by_key(|r| r.1);
    println!(
        "全局轴置换扫描 · {} 帧取样（每帧 2,538 条边）· 排名按撕边总数",
        frames.len()
    );
    for (i, (name, s15, s20, mx)) in results.iter().enumerate() {
        if i < 6 || i >= results.len() - 2 {
            println!("{:>3}. {name} 超1.5 合计 {s15} · 超2 合计 {s20} · 最大 {mx:.2}", i + 1);
        } else if i == 6 {
            println!("    …（中间 40 名略）");
        }
    }
}

/// 逐骨查「这一帧的调色板还是不是刚体」：3×3 与正交的偏离、|det−1|、三轴缩放。
///
/// 为什么要单独查：两端主贡献骨是**同一根骨**的边也被拉开了（wave21 实测占残差的
/// 17~43%）。一根骨的变换若是刚体，同骨两顶点之间的距离**不可能**变——所以要么
/// 调色板带了缩放（`.ani` 的 scale 通道 / 占位复合），要么尺子本身坏了。
fn bone_rigidity(h: &tlbb_core::preview::SkeletonHierarchy, pal: &[[f32; 16]]) {
    let mut rows = Vec::new();
    for (i, m) in pal.iter().enumerate() {
        let col = |c: usize| [m[c], m[4 + c], m[8 + c]];
        let len = |v: [f32; 3]| (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
        let (c0, c1, c2) = (col(0), col(1), col(2));
        let (l0, l1, l2) = (len(c0), len(c1), len(c2));
        let dot = |a: [f32; 3], b: [f32; 3]| a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
        let ortho = dot(c0, c1).abs().max(dot(c1, c2).abs()).max(dot(c0, c2).abs());
        let skew = (l0 - 1.0).abs().max((l1 - 1.0).abs()).max((l2 - 1.0).abs());
        let det = (c0[0] * (c1[1] * c2[2] - c1[2] * c2[1])
            - c0[1] * (c1[0] * c2[2] - c1[2] * c2[0])
            + c0[2] * (c1[0] * c2[1] - c1[1] * c2[0]))
            .abs();
        rows.push((skew.max(ortho), h.bones[i].name.clone(), l0, l1, l2, ortho, det));
    }
    rows.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    println!("骨 | 三轴长度 | 最大不正交 | |det|（按「离刚体最远」排序，前 10）");
    for (worst, name, l0, l1, l2, ortho, det) in rows.iter().take(10) {
        let _ = worst;
        println!("{name} | {l0:.4} {l1:.4} {l2:.4} | {ortho:.4} | {det:.4}");
    }
    let n_rigid = rows.iter().filter(|r| r.0 < 1e-3).count();
    println!("刚体骨（偏离 <1e-3）：{n_rigid} / {} 根", rows.len());
}

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let mesh = arg(&argv, "mesh").expect("要带 --mesh=<路径>");
    let ani = arg(&argv, "ani").expect("要带 --ani=<路径>");
    let step: usize = arg(&argv, "step")
        .map(|s| s.to_string_lossy().parse().unwrap_or(1))
        .unwrap_or(1);

    let raw_mesh = std::fs::read(&mesh).expect("读不到 mesh");
    let raw_ani = std::fs::read(&ani).expect("读不到 ani");
    let layout = parse_mesh(&raw_mesh).expect("mesh 解析失败");
    let h = parse_hierarchy(&raw_mesh).expect("骨架解不出");
    let nodes = parse_nodes(&raw_mesh);
    let a = parse_ani(&raw_ani).expect("ani 解析失败");
    let g = &layout.geometry;
    let 无记录 = h.bones.iter().filter(|b| b.bind.is_none()).count();
    println!(
        "{} · 顶点 {} 面 {} 骨 {}（声明 {}，无 96B 记录 {无记录} 根）· 动作 {} 帧",
        mesh.file_name().unwrap().to_string_lossy(),
        g.positions.len(),
        g.indices.len() / 3,
        h.bones.len(),
        bone_count(&raw_mesh).unwrap_or(0),
        a.frames
    );

    let bind = pose::bind_worlds(&h);
    let anchor = pose::pose_frame(&h, &a, 0);
    // 第三种锚：把 rest.rs 从 `.ani` 静态区反解出的位置补进无记录骨（它们在
    // bind_worlds 里与父骨重合）。只补平移、旋转仍取父骨——这是探针不是口径：
    // 先看撕裂会不会塌，再决定要不要往播放层搬。
    let rebuilt = rest_poses(&raw_ani).and_then(|rests| rebuild_bind_positions(&h, &a, &rests));
    let bind_rest = match &rebuilt {
        Some(r) => {
            let mut m = bind.clone();
            let mut filled = 0usize;
            for (i, bone) in h.bones.iter().enumerate() {
                if bone.bind.is_some() {
                    continue;
                }
                if let Some(p) = r.positions.get(i).copied().flatten() {
                    (m[i][12], m[i][13], m[i][14]) = (p[0], p[1], p[2]);
                    filled += 1;
                }
            }
            println!("静态区反解补上平移的无记录骨：{filled}/{无记录} 根");
            m
        }
        None => {
            println!("静态区反解自检没过，第三种锚不做");
            bind.clone()
        }
    };

    if argv.iter().any(|a| a == "--rsweep") {
        rsweep(&h, &a, &nodes, &g.positions, &g.indices, &anchor);
        return;
    }
    if argv.iter().any(|a| a == "--rigid") {
        let f: usize = arg(&argv, "frame")
            .map(|s| s.to_string_lossy().parse().unwrap_or(0))
            .unwrap_or(0);
        let world = pose::pose_frame(&h, &a, f);
        let pal = pose::skin_palette(&h, &anchor, &world).expect("调色板");
        println!("第 {f} 帧 · frame0 锚的调色板刚体性");
        bone_rigidity(&h, &pal);
        return;
    }
    // 第四口径（假设检验，探针不进判据）：`.ani` 的轨道值**不当局部变换沿父链复合**，
    // 而是直接当这根骨的世界变换（没轨道的骨用 bind 世界矩阵）。
    // 若撕在这个口径下塌下去 ⇒ 轨道存的是绝对值，`compose_worlds` 那一层复合就是错的。
    // 链条体检（纯源数据，不涉及播放口径；上一版这样写是恒等式，已改）：
    // 每根 96B 记录存的是**自己那根骨的世界绑定逆**，求逆就拿到骨位——这跟父骨链无关。
    // 所以能这么问：解析出来的父亲，在「按距离该排第几」上排第几？
    // 链挂对了，父亲本该是最近的那几根；排到十名开外就是**挂错父**。
    if argv.iter().any(|x| x == "--chaincheck") {
        let pos = |i: usize| -> Option<[f32; 3]> {
            let b = h.bones[i].bind?;
            let inv = pose::mat_inverse_affine(&b)?;
            Some([inv[12], inv[13], inv[14]])
        };
        let rec: Vec<usize> = (0..h.bones.len()).filter(|&i| pos(i).is_some()).collect();
        let mut ranks: Vec<(String, usize, f64, usize)> = Vec::new();
        let mut no_rec_parent = 0usize;
        let mut hist = std::collections::BTreeMap::new();
        for &c in &rec {
            let Some(pi) = h.bones[c].parent else { continue };
            let Some(pp) = pos(pi) else { no_rec_parent += 1; continue };
            
            let Some(cq) = pos(c) else { continue };
            let dme = ((pp[0] - cq[0]).powi(2) + (pp[1] - cq[1]).powi(2) + (pp[2] - cq[2]).powi(2)).sqrt() as f64;
            let mut better = 0usize;
            for &o in &rec {
                if o == c || o == pi {
                    continue;
                }
                let Some(oq) = pos(o) else { continue };
                let dd = ((oq[0] - cq[0]).powi(2) + (oq[1] - cq[1]).powi(2) + (oq[2] - cq[2]).powi(2)).sqrt() as f64;
                if dd < dme {
                    better += 1;
                }
            }
            *hist.entry(better + 1).or_insert(0usize) += 1;
            ranks.push((h.bones[c].name.clone(), better + 1, dme, rec.len()));
        }
        ranks.sort_by(|x, y| y.1.cmp(&x.1));
        println!("链的拓扑体检：解析出的父亲按「离这根骨的骨位有多近」能排第几（有记录的骨 {} 根）", rec.len());
        println!("父亲没记录、没法比的骨：{no_rec_parent} 根");
        let mut keys: Vec<&usize> = hist.keys().collect();
        keys.sort();
        for k in keys {
            println!("  排名 {:>3} ：{} 根", k, hist[k]);
        }
        println!("排最差的前 10 根（骨名 · 父亲排名 · 到父亲的骨位距离）：");
        for (n, r, d, _) in ranks.iter().take(10) {
            println!("  {:<24} 第 {:>3} 名 · {:.3}", n, r, d);
        }
        return;
    }
    // 边的分类账（2026-10-12）：把每条三角形边按「两端的带权重表骨集合」分四类，
    // 逐类量拉伸，两种播放口径各跑一遍。要分开的两件事——
    //   * **覆盖不全**：一端或两端没有权重表，那端按口径保持存储位不动，边长当然
    //     变——这是缺数据，不是摆错，不能拿来判合成律；
    //   * **骨与骨之间的相对变换**：两端都有表且集合不同，边长变化才由合成律决定。
    // 「两端同集」那档同时是尺子的自检：同一根骨刚体保距 ⇒ 该档最大倍数应贴着 1。
    if argv.iter().any(|x| x == "--edgeclass") {
        use std::collections::BTreeMap;
        let mut bidx: BTreeMap<&str, usize> = BTreeMap::new();
        for (i, b) in h.bones.iter().enumerate() {
            bidx.insert(b.name.as_str(), i);
        }
        // 逐顶点的带表骨（w>0 才占位，与 `posed_vertices` 同口径）
        let mut vbones: Vec<Vec<usize>> = vec![Vec::new(); g.positions.len()];
        for nd in &nodes {
            let Some(skin) = &nd.skin else { continue };
            let Some(&bi) = bidx.get(nd.name.as_str()) else { continue };
            for (&v, &w) in skin.vertices.iter().zip(skin.weights.iter()) {
                let vi = v as usize;
                if vi < vbones.len() && w.is_finite() && w > 0.0 {
                    vbones[vi].push(bi);
                }
            }
        }
        let cov = vbones.iter().filter(|x| !x.is_empty()).count();
        let n = g.positions.len();
        println!("顶点 {n} 个 · 带表 {cov} 个 · 无表 {} 个（覆盖 {:.1}%）", n - cov, 100.0 * cov as f64 / n as f64);
        println!("带表的骨 {} 根（节点记录 {} 条）", nodes.iter().filter(|x| x.skin.is_some()).count(), nodes.len());

        let dist = |a: &[f32; 3], b: &[f32; 3]| -> f64 {
            ((b[0] - a[0]).powi(2) + (b[1] - a[1]).powi(2) + (b[2] - a[2]).powi(2)).sqrt() as f64
        };
        let class = |i: usize, j: usize| -> &'static str {
            let (x, y) = (&vbones[i], &vbones[j]);
            if x.is_empty() && y.is_empty() {
                "两端都无表"
            } else if x.is_empty() || y.is_empty() {
                "一端无表"
            } else if x == y {
                "两端同骨"
            } else if x.iter().any(|k| y.contains(k)) {
                "两端交叠"
            } else {
                "两端异骨"
            }
        };
        let frames: Vec<usize> = (0..a.frames).step_by(step.max(1)).collect();
        for mode in 0..2u8 {
            let tag = if mode == 0 {
                "现口径（轨道当局部·沿父链复合）"
            } else {
                "试错口径（轨道直接当世界·无轨道骨用 bind 世界）"
            };
            let mut agg: BTreeMap<&'static str, (usize, usize, usize, f64)> = BTreeMap::new();
            let mut pairs: BTreeMap<(String, String), (usize, f64)> = BTreeMap::new();
            for &f in &frames {
                let world = if mode == 0 {
                    pose::pose_frame(&h, &a, f)
                } else {
                    let mut out = bind.clone();
                    for t in &a.tracks {
                        if t.rotations.is_empty() || t.positions.is_empty() || t.scales.is_empty() {
                            continue;
                        }
                        if let Some(i) = h.bones.iter().position(|x| x.name == t.bone) {
                            let k = f.min(t.rotations.len() - 1)
                                .min(t.positions.len() - 1)
                                .min(t.scales.len() - 1);
                            out[i] = pose::trs_matrix(&t.rotations[k], t.positions[k], t.scales[k]);
                        }
                    }
                    out
                };
                let Some(pal) = pose::skin_palette(&h, &anchor, &world) else { continue };
                let Some(posed) = pose::posed_vertices(&h, &pal, &nodes, &g.positions) else { continue };
                for tri in g.indices.chunks_exact(3) {
                    for &(i, j) in &[(tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])] {
                        let (i, j) = (i as usize, j as usize);
                        let len0 = dist(&g.positions[i], &g.positions[j]);
                        if len0 < 1e-4 {
                            continue;
                        }
                        let r = dist(&posed[i], &posed[j]) / len0;
                        let c = class(i, j);
                        let e = agg.entry(c).or_insert((0, 0, 0, 0.0));
                        e.0 += 1;
                        if r > 1.5 {
                            e.1 += 1;
                        }
                        if r > 2.0 {
                            e.2 += 1;
                        }
                        if r > e.3 {
                            e.3 = r;
                        }
                        if c == "两端异骨" && r > 2.0 {
                            let a0 = h.bones[vbones[i][0]].name.clone();
                            let b0 = h.bones[vbones[j][0]].name.clone();
                            let key = if a0 <= b0 { (a0, b0) } else { (b0, a0) };
                            let p = pairs.entry(key).or_insert((0, 0.0));
                            p.0 += 1;
                            p.1 = p.1.max(r);
                        }
                    }
                }
            }
            println!("\n{tag} · {} 帧取样（边次 = 边数 × 取样帧数）", frames.len());
            let mut all = 0usize;
            let mut torn = 0usize;
            for (c, (e, o15, o20, mx)) in &agg {
                all += e;
                torn += o20;
                println!("  {:<6} 边次 {:>8} · 超1.5 {:>7} · 超2 {:>7} · 最大 {:>9.2}", c, e, o15, o20, mx);
            }
            println!("  合计 {all} 边次 · 超2 的占 {:.1}%", 100.0 * torn as f64 / all.max(1) as f64);
            if !pairs.is_empty() {
                let mut v: Vec<_> = pairs.into_iter().collect();
                v.sort_by(|x, y| y.1 .1.partial_cmp(&x.1 .1).unwrap());
                println!("  异骨超 2 倍的骨对（骨A · 骨B · 边次 · 最大倍数）：");
                for ((a0, b0), (cnt, mx)) in v.iter().take(8) {
                    println!("    {a0} × {b0} · {cnt} · {mx:.2}");
                }
            }
        }
        return;
    }
    if argv.iter().any(|x| x == "--worldmode") {
        let wd = |fr: usize| -> Vec<[f32; 16]> {
            let mut out = bind.clone();
            for t in &a.tracks {
                if t.bone.is_empty() || t.rotations.is_empty() || t.positions.is_empty() || t.scales.is_empty() {
                    continue;
                }
                if let Some(i) = h.bones.iter().position(|x| x.name == t.bone) {
                    let k = fr.min(t.rotations.len() - 1).min(t.positions.len() - 1).min(t.scales.len() - 1);
                    out[i] = pose::trs_matrix(&t.rotations[k], t.positions[k], t.scales[k]);
                }
            }
            out
        };
        let anchor_w = wd(0);
        let one = |anch: &[[f32; 16]], world: &[[f32; 16]]| -> String {
            match pose::skin_palette(&h, anch, world)
                .and_then(|pal| pose::posed_vertices(&h, &pal, &nodes, &g.positions))
            {
                Some(posed) => {
                    let (o15, o20, max) = stretch(&g.positions, &posed, &g.indices);
                    format!("{o15}/{o20}/{max:.2}")
                }
                None => "算不出".to_string(),
            }
        };
        println!("帧 | 现口径（轨道当局部·沿父链复合） | 试错口径（轨道直接当世界）  （超1.5/超2/最大倍数）");
        for f in (0..a.frames).step_by(step.max(1)) {
            let cur = pose::pose_frame(&h, &a, f);
            let w = wd(f);
            println!("{f:3} | {} | {}", one(&anchor, &cur), one(&anchor_w, &w));
        }
        return;
    }
    println!("帧 | frame0 锚(现口径) | bind 锚 | bind 锚+静态区补位   （超1.5 边数 / 超2 / 最大倍数）");
    for f in (0..a.frames).step_by(step.max(1)) {
        let world = pose::pose_frame(&h, &a, f);
        let mut line = format!("{f:3}");
        for (name, anch) in
            [("frame0", &anchor), ("bind", &bind), ("bind+rest", &bind_rest)]
        {
            let out = match pose::skin_palette(&h, anch, &world) {
                Some(palette) => match pose::posed_vertices(&h, &palette, &nodes, &g.positions) {
                    Some(posed) => {
                        let (o15, o20, max) = stretch(&g.positions, &posed, &g.indices);
                        format!("{o15}/{o20}/{max:.2}")
                    }
                    None => "摆不出".to_string(),
                },
                None => "解不出".to_string(),
            };
            let _ = name;
            line.push_str(&format!(" | {out}"));
        }
        println!("{line}");
    }
}
