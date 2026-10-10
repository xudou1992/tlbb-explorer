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
