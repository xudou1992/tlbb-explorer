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
