//! 单条 MIN3 动作逐帧撕边 + 跳变骨定位。
//!
//! 用法（crates/core 下）：
//! ```text
//! cargo run --offline --release --example min3_frame_probe -- data1 000b7690ae6394ea data_1 45f6b238dc62318a
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{attach_bone_skin, parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose};

fn qangle(a: &[f32; 4], b: &[f32; 4]) -> f32 {
    let d: f32 = (0..4).map(|k| a[k] * b[k]).sum::<f32>().abs().min(1.0);
    2.0 * d.acos().to_degrees()
}

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    if a.len() < 4 {
        eprintln!("需要 4 个参数：网格pak 网格哈希 动作pak 动作哈希");
        return;
    }
    let root = PathBuf::from("D:/TLGL");
    let open = |name: &str| Pak::open(root.join(format!("{name}.pak"))).expect("包打不开");
    let mp = open(&a[0]);
    let ap = open(&a[2]);
    let mh = u64::from_str_radix(&a[1], 16).expect("网格哈希");
    let ah = u64::from_str_radix(&a[3], 16).expect("动作哈希");
    let rm = mp.records().find(|r| r.hash == mh && r.stored > 0).expect("网格不在包里");
    let ra = ap.records().find(|r| r.hash == ah && r.stored > 0).expect("动作不在包里");
    let mraw = payload::decode(&mp, &rm).expect("网格解压失败").bytes;
    let araw = payload::decode(&ap, &ra).expect("动作解压失败").bytes;
    println!("动作容器 {}", String::from_utf8_lossy(&araw[0x8c..0x90]));
    let min3 = araw.get(0x8c..0x90) == Some(&b"MIN3"[..]);
    let layout = parse_mesh(&mraw).expect("网格解析失败");
    let h = parse_hierarchy(&mraw).expect("骨架解析失败");
    let anim = parse_ani(&araw).expect("动作解析失败");
    let nodes = attach_bone_skin(&h, &parse_nodes(&mraw), &mraw);
    let g = &layout.geometry;
    println!(
        "骨 {} 帧 {} 轨道 {} · 顶点 {} 三角形 {} · 骨架 {} 根",
        anim.bones,
        anim.frames,
        anim.tracks.len(),
        g.positions.len(),
        g.indices.len() / 3,
        h.bones.len()
    );
    {
        let mut rc: Vec<usize> = anim.tracks.iter().map(|t| t.rotations.len()).collect();
        rc.sort_unstable();
        let mut pc: Vec<usize> = anim.tracks.iter().map(|t| t.positions.len()).collect();
        pc.sort_unstable();
        println!(
            "帧数 {} · 旋转按键数 min/中位/max = {}/{}/{} · 位移按键数 min/中位/max = {}/{}/{} · 按键数<帧数的轨道 {} 条",
            anim.frames,
            rc[0],
            rc[rc.len() / 2],
            rc[rc.len() - 1],
            pc[0],
            pc[pc.len() / 2],
            pc[pc.len() - 1],
            rc.iter().filter(|n| **n < anim.frames).count()
        );
    }
    let total = |a: &tlbb_core::preview::Anim| -> usize {
        let mut sum = 0usize;
        for f in 0..a.frames {
            let Some(pal) = pose::reanchored_palette(&h, a, f) else { continue };
            let Some(posed) = pose::posed_vertices(&h, &pal, &nodes, &g.positions) else { continue };
            sum += pose::edge_stretch(&g.positions, &posed, &g.indices).over15;
        }
        sum
    };
    // 骨名错位 A/B：δ=1（现口径，名表 0xF0 起）vs δ=0（0xD2 起）。
    let mut d0 = anim.clone();
    for i in 0..d0.tracks.len() {
        let o = 0xd2 + i * 30;
        d0.tracks[i].bone = match araw.get(o..o + 30) {
            Some(b) => {
                let end = b.iter().position(|&c| c == 0).unwrap_or(30);
                String::from_utf8_lossy(&b[..end]).into_owned()
            }
            None => String::new(),
        };
    }
    println!("全帧撕边合计：δ=1 现口径 {} · δ=0 同名同序 {}", total(&anim), total(&d0));
    // 逐骨绑定对账（δ=1 口径）：位移/旋转与 .mesh 绑定局部的差。
    // 轨道名唯一性：按名字挂骨的前提是「一根骨一个名字」。
    {
        use std::collections::HashMap as M;
        let mut seen: M<&str, usize> = M::new();
        let mut empty = 0usize;
        for t in &anim.tracks {
            if t.bone.is_empty() {
                empty += 1;
            } else {
                *seen.entry(t.bone.as_str()).or_default() += 1;
            }
        }
        let dup: Vec<(&str, usize)> = seen.iter().filter(|(_, c)| **c > 1).map(|(n, c)| (*n, *c)).collect();
        let names: std::collections::HashSet<&str> = h.bones.iter().map(|b| b.name.as_str()).collect();
        let miss = seen.keys().filter(|n| !names.contains(**n)).count();
        let dup_bones = {
            let mut m: M<&str, usize> = M::new();
            for b in &h.bones {
                *m.entry(b.name.as_str()).or_default() += 1;
            }
            m.values().filter(|c| **c > 1).count()
        };
        println!(
            "轨道名：空 {} · 重复 {} 种 {:?} · 骨架里没有 {} 种 · 骨架重名 {} 种",
            empty,
            dup.len(),
            dup.iter().take(6).collect::<Vec<_>>(),
            miss,
            dup_bones
        );
    }
    let mut al = tlbb_core::preview::rest::align_outliers(&araw, &h);
    let bad_rot = al.iter().filter(|x| x.2 > 10.0).count();
    let bad_pos = al.iter().filter(|x| x.1 > 0.05).count();
    println!("对账 {} 根：旋转差>10° {} 根 · 位移差>0.05 {} 根", al.len(), bad_rot, bad_pos);
    al.sort_by(|x, y| y.2.total_cmp(&x.2));
    println!("旋转差最大的 12 根（名称 / 旋转° / 位移差）:");
    for (n, dp, dr, _dw, _rw) in al.iter().take(12) {
        println!("  {n:32} {dr:8.2}°  {dp:.4}");
    }
    // 撕边按「主权重骨」归属：顶点→骨的影响表在节点记录里（按骨稀疏存）。
    let mut owner: Vec<Option<(String, f32)>> = vec![None; g.positions.len()];
    for nd in &nodes {
        if let Some(sk) = &nd.skin {
            for (k, &v) in sk.vertices.iter().enumerate() {
                let w = sk.weights.get(k).copied().unwrap_or(0.0);
                let vi = v as usize;
                if vi >= owner.len() {
                    continue;
                }
                if owner[vi].as_ref().map(|(_, ow)| w > *ow).unwrap_or(true) {
                    owner[vi] = Some((nd.name.clone(), w));
                }
            }
        }
    }
    // 解析器眼里这条变体记录到底有没有被认出来？
    {
        let hit = nodes.iter().find(|nd| nd.name == "bip001_prop002");
        println!(
            "节点记录 {} 条（带影响表 {} 条）· bip001_prop002 在节点里？{}",
            nodes.len(),
            nodes.iter().filter(|nd| nd.skin.is_some()).count(),
            match hit {
                None => "不在".to_string(),
                Some(nd) => format!("在，skin={}", if nd.skin.is_some() { "有" } else { "无" }),
            }
        );
    }
    // 权重覆盖：没被任何影响表盖住的顶点会被兜底挂到根骨/恒等，邻居一动就被拉开。
    {
        let mut sum_w: Vec<f32> = vec![0.0; g.positions.len()];
        let mut cov = 0usize;
        for nd in &nodes {
            if let Some(sk) = &nd.skin {
                for (k, &v) in sk.vertices.iter().enumerate() {
                    let vi = v as usize;
                    if vi < sum_w.len() {
                        sum_w[vi] += sk.weights.get(k).copied().unwrap_or(0.0);
                    }
                }
            }
        }
        let hard = sum_w.iter().filter(|w| **w >= 0.99).count();
        let blended = sum_w.iter().filter(|w| **w > 0.0 && **w < 0.99).count();
        let zero = sum_w.iter().filter(|w| **w <= 0.0).count();
        cov = zero;
        // 未覆盖顶点是连成一片（某个子网格）还是散着？
        let mut runs: Vec<(usize, usize)> = Vec::new();
        let mut i = 0usize;
        while i < sum_w.len() {
            if sum_w[i] <= 0.0 {
                let st = i;
                while i < sum_w.len() && sum_w[i] <= 0.0 {
                    i += 1;
                }
                runs.push((st, i - st));
            } else {
                i += 1;
            }
        }
        runs.sort_by(|a, b| b.1.cmp(&a.1));
        println!(
            "  未覆盖分成 {} 段，最长几段（起点,长度）：{:?}；单点段 {} 个",
            runs.len(),
            runs.iter().take(5).collect::<Vec<_>>(),
            runs.iter().filter(|r| r.1 == 1).count()
        );
        // 硬权重（单骨、权重≥0.99）占比：硬绑在关节处必然开缝，是「散架」的另一个候选解释。
        let mut single = 0usize;
        let mut multi = 0usize;
        let mut cnt: Vec<usize> = vec![0; g.positions.len()];
        let mut maxw: Vec<f32> = vec![0.0; g.positions.len()];
        for nd in &nodes {
            if let Some(sk) = &nd.skin {
                for (k, &v) in sk.vertices.iter().enumerate() {
                    let vi = v as usize;
                    if vi < cnt.len() {
                        cnt[vi] += 1;
                        maxw[vi] = maxw[vi].max(sk.weights.get(k).copied().unwrap_or(0.0));
                    }
                }
            }
        }
        for vi in 0..cnt.len() {
            if cnt[vi] == 0 {
                continue;
            }
            if cnt[vi] == 1 && maxw[vi] >= 0.99 {
                single += 1;
            } else {
                multi += 1;
            }
        }
        println!(
            "权重覆盖：顶点 {} · 未被任何表盖住 {}（{:.1}%）· 权重和≈1 的 {} · 有表但和<1 的 {} · 单骨硬绑 {} · 多骨 {}",
            g.positions.len(),
            cov,
            cov as f64 * 100.0 / g.positions.len() as f64,
            hard,
            blended,
            single,
            multi
        );
    }
    // A/B：权重和 < 1 的顶点，归一化（除以和）vs unify_weights 的「差额挂根骨」。
    {
        let mut idx: HashMap<&str, usize> = HashMap::new();
        for (i, b) in h.bones.iter().enumerate() {
            idx.insert(b.name.as_str(), i);
        }
        let root = h.bones.iter().position(|b| b.parent.is_none()).unwrap_or(0);
        let mut lists: Vec<Vec<(usize, f32)>> = vec![Vec::new(); g.positions.len()];
        for nd in &nodes {
            let Some(sk) = &nd.skin else { continue };
            let Some(&bi) = idx.get(nd.name.as_str()) else { continue };
            for (&v, &w) in sk.vertices.iter().zip(sk.weights.iter()) {
                if (v as usize) < lists.len() && w > 0.0 {
                    lists[v as usize].push((bi, w));
                }
            }
        }
        let xf = |m: &[f32; 16], p: [f32; 3]| {
            [
                p[0] * m[0] + p[1] * m[4] + p[2] * m[8] + m[12],
                p[0] * m[1] + p[1] * m[5] + p[2] * m[9] + m[13],
                p[0] * m[2] + p[1] * m[6] + p[2] * m[10] + m[14],
            ]
        };
        let (mut sn, mut sf) = (0usize, 0usize);
        for f in 0..anim.frames {
            let Some(pal) = pose::reanchored_palette(&h, &anim, f) else { continue };
            let mut vn = g.positions.clone();
            let mut vf = g.positions.clone();
            for (vi, list) in lists.iter().enumerate() {
                let total: f32 = list.iter().map(|(_, w)| *w).sum();
                if total <= 1e-6 {
                    continue;
                }
                let p = g.positions[vi];
                let (mut an, mut af) = ([0f32; 3], [0f32; 3]);
                for &(j, w) in list {
                    let t = xf(&pal[j], p);
                    for k in 0..3 {
                        an[k] += (w / total) * t[k];
                        af[k] += w * t[k];
                    }
                }
                if total < 1.0 {
                    let t = xf(&pal[root], p);
                    for k in 0..3 {
                        af[k] += (1.0 - total) * t[k];
                    }
                }
                vn[vi] = an;
                vf[vi] = af;
            }
            sn += pose::edge_stretch(&g.positions, &vn, &g.indices).over15;
            sf += pose::edge_stretch(&g.positions, &vf, &g.indices).over15;
        }
        println!("A/B 归一化 {sn} · 差额挂根骨 {sf}");
    }
    // 组合口径：共轭 + 反序复合（W = 父世界 · 局部）。单变量测试可能互相掩盖，这组没有单独验过。
    {
        let compose_rev = |h: &tlbb_core::preview::SkeletonHierarchy, local: &[[f32; 16]]| {
            let n = h.bones.len();
            let mut w = vec![pose::mat_identity(); n];
            let mut done = vec![false; n];
            for _ in 0..=n {
                let mut moved = false;
                for i in 0..n {
                    if done[i] { continue; }
                    match h.bones[i].parent {
                        None => { w[i] = local[i]; done[i] = true; moved = true; }
                        Some(p) if done[p] => { w[i] = pose::mat_mul(&w[p], &local[i]); done[i] = true; moved = true; }
                        Some(_) => {}
                    }
                }
                if !moved { break; }
            }
            w
        };
        let base_anchor = {
            let mut local = vec![pose::mat_identity(); h.bones.len()];
            for t in &anim.tracks {
                if t.bone.is_empty() || t.rotations.is_empty() { continue; }
                let Some(j) = h.bones.iter().position(|b| b.name == t.bone) else { continue };
                let k = 0.min(t.rotations.len() - 1);
                local[j] = pose::trs_matrix(&t.rotations[k], t.positions[k], t.scales[k]);
            }
            compose_rev(&h, &local)
        };
        for (tag, conj) in [("共轭+反序", true), ("原样+反序", false)] {
            let mut sum = 0usize;
            for f in 0..anim.frames {
                let mut local = vec![pose::mat_identity(); h.bones.len()];
                for t in &anim.tracks {
                    if t.bone.is_empty() || t.rotations.is_empty() { continue; }
                    let Some(j) = h.bones.iter().position(|b| b.name == t.bone) else { continue };
                    let k = f.min(t.rotations.len() - 1);
                    let mut q = t.rotations[k];
                    if conj { q = [-q[0], -q[1], -q[2], q[3]]; }
                    local[j] = pose::trs_matrix(&q, t.positions[k], t.scales[k]);
                }
                let w = compose_rev(&h, &local);
                let Some(pal) = pose::skin_palette(&h, &base_anchor, &w) else { continue };
                let Some(posed) = pose::posed_vertices(&h, &pal, &nodes, &g.positions) else { continue };
                sum += pose::edge_stretch(&g.positions, &posed, &g.indices).over15;
            }
            println!("{tag} → 全帧撕边 {sum}");
        }
    }
    // 锚口径对照：第 0 帧锚（预览）vs 网格绑定锚（游戏真正的蒙皮口径）。
    {
        let bind = pose::bind_worlds(&h);
        let mut sum_bind = 0usize;
        for f in 0..anim.frames {
            let w = pose::pose_frame(&h, &anim, f);
            let Some(pal) = pose::skin_palette(&h, &bind, &w) else { continue };
            let Some(posed) = pose::posed_vertices(&h, &pal, &nodes, &g.positions) else { continue };
            sum_bind += pose::edge_stretch(&g.positions, &posed, &g.indices).over15;
        }
        println!("绑定锚（bind⁻¹·world）→ 全帧撕边 {sum_bind}");
    }
    // 父骨链合理性：绑定世界下，子骨到父骨的距离不该接近整个模型尺度。
    {
        let bw = pose::bind_worlds(&h);
        let mut d: Vec<f32> = Vec::new();
        for (j, b) in h.bones.iter().enumerate() {
            let Some(p) = b.parent else { continue };
            let a = [bw[j][12], bw[j][13], bw[j][14]];
            let c = [bw[p][12], bw[p][13], bw[p][14]];
            d.push(((a[0]-c[0]).powi(2) + (a[1]-c[1]).powi(2) + (a[2]-c[2]).powi(2)).sqrt());
        }
        let (mut lo, mut hi) = ([f32::MAX; 3], [f32::MIN; 3]);
        for v in &g.positions { for k in 0..3 { lo[k] = lo[k].min(v[k]); hi[k] = hi[k].max(v[k]); } }
        let bbox = ((hi[0]-lo[0]).powi(2) + (hi[1]-lo[1]).powi(2) + (hi[2]-lo[2]).powi(2)).sqrt();
        let mut far = 0usize;
        for x in &d { if *x > bbox * 0.5 { far += 1; } }
        d.sort_by(|a, b| a.total_cmp(b));
        println!(
            "父骨距离：中位 {:.3} · p90 {:.3} · 最大 {:.3} · 模型对角线 {:.2} · 超过对角线一半的 {} 根 / {}",
            d.get(d.len()/2).copied().unwrap_or(0.0),
            d.get(d.len()*9/10).copied().unwrap_or(0.0),
            d.last().copied().unwrap_or(0.0), bbox, far, d.len()
        );
    }
    // 每根骨偏好的轨道偏移（±2）：若整份文件偏向与全局约定不同的偏移，就是分段错位。
    {
        let al = tlbb_core::preview::rest::align_best_delta(&araw, &h, 2);
        let mut hist = std::collections::BTreeMap::new();
        for (_, di, _, _) in &al {
            *hist.entry(*di).or_insert(0usize) += 1;
        }
        println!("偏移偏好直方图（骨数 {})：{hist:?}", al.len());
        let mut worst: Vec<(String, isize, f32)> = al.iter().map(|(n, d, r, _)| (n.clone(), *d, *r)).collect();
        worst.sort_by(|a, b| b.2.total_cmp(&a.2));
        println!("偏差最大的 6 根：{:?}", worst.iter().take(6).collect::<Vec<_>>());
    }
    // 共轭（左手/右手系约定）：q → (-x,-y,-z,w)
    {
        let mut v = anim.clone();
        for t in v.tracks.iter_mut() {
            for q in t.rotations.iter_mut() {
                *q = [-q[0], -q[1], -q[2], q[3]];
            }
        }
        let mut sum = 0usize;
        for f in 0..v.frames {
            let Some(pal) = pose::reanchored_palette(&h, &v, f) else { continue };
            let Some(posed) = pose::posed_vertices(&h, &pal, &nodes, &g.positions) else { continue };
            sum += pose::edge_stretch(&g.positions, &posed, &g.indices).over15;
        }
        println!("共轭 → 全帧撕边 {sum}");
    }
    // 四元数分量顺序扫描：unit 长且帧间平滑，但整体旋转可能完全不对（D3DX 是 w 在前）。
    {
        let perms: [[usize; 4]; 4] = [[0, 1, 2, 3], [3, 0, 1, 2], [1, 2, 3, 0], [2, 3, 0, 1]];
        for (k, pm) in perms.iter().enumerate() {
            let mut v = anim.clone();
            for t in v.tracks.iter_mut() {
                for q in t.rotations.iter_mut() {
                    *q = [q[pm[0]], q[pm[1]], q[pm[2]], q[pm[3]]];
                }
            }
            let mut sum = 0usize;
            for f in 0..v.frames {
                let Some(pal) = pose::reanchored_palette(&h, &v, f) else { continue };
                let Some(posed) = pose::posed_vertices(&h, &pal, &nodes, &g.positions) else { continue };
                sum += pose::edge_stretch(&g.positions, &posed, &g.indices).over15;
            }
            println!("分量序 {pm:?} → 全帧撕边 {sum}");
            let _ = k;
        }
    }
    // 单骨随帧曲线：看主骨是慢漂移还是乱跳。
    {
        for bone in ["bip001_pelvis", "bip001", "bone052"] {
            if let Some(t) = anim.tracks.iter().find(|t| t.bone == bone && !t.rotations.is_empty()) {
                let mut line = String::new();
                for f in (0..anim.frames).step_by((anim.frames / 8).max(1)) {
                    let q0 = t.rotations[0];
                    let q = t.rotations[f];
                    let dot: f32 = (0..4).map(|k| q0[k] * q[k]).sum::<f32>().abs().min(1.0);
                    line.push_str(&format!("{}:{:.0} ", f, 2.0 * dot.acos().to_degrees()));
                }
                println!("角度曲线 {bone}: {line}");
            }
        }
    }
    // 锚帧扫描：如果第 0 帧是异常帧（绑定帧/占位帧），换个锚撕边会塌。
    for anchor_f in 0..4usize.min(anim.frames) {
        let aw = pose::pose_frame(&h, &anim, anchor_f);
        let mut sum = 0usize;
        for f in 0..anim.frames {
            let w = pose::pose_frame(&h, &anim, f);
            let Some(pal) = pose::skin_palette(&h, &aw, &w) else { continue };
            let Some(posed) = pose::posed_vertices(&h, &pal, &nodes, &g.positions) else { continue };
            sum += pose::edge_stretch(&g.positions, &posed, &g.indices).over15;
        }
        println!("锚=第 {anchor_f} 帧 → 全帧撕边 {sum}");
    }
    let mut per_frame = Vec::new();
    for f in 0..anim.frames {
        // 与动作页同口径：以第 0 帧为锚（reanchored_palette）。
        let Some(pal) = pose::reanchored_palette(&h, &anim, f) else {
            println!("帧 {f}: 调色板算不出");
            continue;
        };
        let Some(posed) = pose::posed_vertices(&h, &pal, &nodes, &g.positions) else {
            println!("帧 {f}: 顶点算不出");
            continue;
        };
        let s = pose::edge_stretch(&g.positions, &posed, &g.indices);
        per_frame.push((f, s.over15));
    }
    for (f, n) in &per_frame {
        println!("帧 {:3}: 撕边 {:6}", f, n);
    }
    let Some(&(worst, _)) = per_frame.iter().max_by_key(|(_, n)| *n) else { return };
    println!("撕边最狠帧 = {worst}");
    if let Some(pal) = pose::reanchored_palette(&h, &anim, worst) {
        if let Some(posed) = pose::posed_vertices(&h, &pal, &nodes, &g.positions) {
            let mut by_bone: HashMap<String, usize> = HashMap::new();
            for tri in g.indices.chunks(3) {
                for k in 0..3 {
                    let (i, j) = (tri[k] as usize, tri[(k + 1) % 3] as usize);
                    if i >= posed.len() || j >= posed.len() {
                        continue;
                    }
                    let (a, b) = (g.positions[i], g.positions[j]);
                    let (pa, pb) = (posed[i], posed[j]);
                    let l0 = ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt();
                    if l0 < 1e-4 {
                        continue;
                    }
                    let l1 = ((pa[0] - pb[0]).powi(2) + (pa[1] - pb[1]).powi(2) + (pa[2] - pb[2]).powi(2)).sqrt();
                    if l1 / l0 <= 1.5 {
                        continue;
                    }
                    if let Some((n, _)) = &owner[i] {
                        *by_bone.entry(n.clone()).or_default() += 1;
                    }
                    if let Some((n, _)) = &owner[j] {
                        *by_bone.entry(n.clone()).or_default() += 1;
                    }
                }
            }
            let mut v: Vec<_> = by_bone.into_iter().collect();
            v.sort_by(|a, b| b.1.cmp(&a.1));
            println!("帧 {worst} 撕边按主权重骨归属（前 12 根）:");
            for (n, c) in v.iter().take(12) {
                println!("  {n:32} {c:6} 条");
            }
            // 对前 5 根「撕得最狠」的骨逐项体检：有没有轨道、轨道值动多少、父骨情况。
            // 自洽判据：权重全挂在「该帧调色板≈恒等」的骨上的顶点，必须原地不动。
            {
                let mut n_id = 0usize;
                let mut moved: Vec<(usize, f32, String)> = Vec::new();
                for (vi, own) in owner.iter().enumerate() {
                    let Some((bn, w)) = own else { continue };
                    if *w < 0.99 {
                        continue;
                    }
                    let Some(j) = h.bones.iter().position(|b| &b.name == bn) else { continue };
                    let m = pal[j];
                    let rot_ang = (((m[0] + m[5] + m[10]) - 1.0) / 2.0).clamp(-1.0, 1.0).acos().to_degrees();
                    let tr = (m[12] * m[12] + m[13] * m[13] + m[14] * m[14]).sqrt();
                    if rot_ang > 0.5 || tr > 1e-4 {
                        continue; // 这根骨该帧确实在动，不参与判据
                    }
                    n_id += 1;
                    if vi >= posed.len() {
                        continue;
                    }
                    let (a, b) = (g.positions[vi], posed[vi]);
                    let d = ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt();
                    if d > 1e-4 {
                        moved.push((vi, d, bn.clone()));
                    }
                }
                moved.sort_by(|x, y| y.1.total_cmp(&x.1));
                println!(
                    "自洽判据（帧 {worst}）：挂在恒等调色板骨上的单骨顶点 {n_id} 个，被移动的 {} 个（最大 {}）",
                    moved.len(),
                    moved.first().map(|(vi, d, bn)| format!("{d:.4} @顶点{vi} 骨{bn}")).unwrap_or_else(|| "无".into())
                );
            }
            let name2idx: HashMap<&str, usize> =
                h.bones.iter().enumerate().map(|(i, b)| (b.name.as_str(), i)).collect();
            for (n, c) in v.iter().take(5) {
                let Some(&j) = name2idx.get(n.as_str()) else {
                    println!("  体检 {n}: 骨架里没这根骨");
                    continue;
                };
                let tr = anim.tracks.iter().find(|t| &t.bone == n);
                let (has_track, drot, dpos) = match tr {
                    Some(t) if !t.rotations.is_empty() => {
                        let q0 = t.rotations[0];
                        let q1 = t.rotations[worst.min(t.rotations.len() - 1)];
                        let dot: f32 = (0..4).map(|k| q0[k] * q1[k]).sum::<f32>().abs().min(1.0);
                        let p0 = t.positions[0];
                        let p1 = t.positions[worst.min(t.positions.len() - 1)];
                        (
                            true,
                            2.0 * dot.acos().to_degrees(),
                            ((p1[0] - p0[0]).powi(2) + (p1[1] - p0[1]).powi(2) + (p1[2] - p0[2]).powi(2)).sqrt(),
                        )
                    }
                    _ => (false, f32::NAN, f32::NAN),
                };
                let par = h.bones[j].parent.map(|p| h.bones[p].name.clone()).unwrap_or_default();
                let par_track = h.bones[j]
                    .parent
                    .map(|p| anim.tracks.iter().any(|t| t.bone == h.bones[p].name && !t.rotations.is_empty()))
                    .unwrap_or(false);
                println!(
                    "  体检 {n}（#{j}，撕边 {c}）：有轨道 {has_track} · 该帧相对第 0 帧 转 {drot:.1}° 动 {dpos:.3} · 父骨 {par}（父有轨道 {par_track}）· 自有 bind {}",
                    h.bones[j].bind.is_some()
                );
            }
            // 每根骨相对第 0 帧的绝对转角（调色板旋转部分）。
            let mut ang: Vec<(String, f32)> = Vec::new();
            for (i, m) in pal.iter().enumerate() {
                let tr = m[0] + m[5] + m[10];
                let c = ((tr - 1.0) / 2.0).clamp(-1.0, 1.0);
                ang.push((h.bones[i].name.clone(), c.acos().to_degrees()));
            }
            ang.sort_by(|a, b| b.1.total_cmp(&a.1));
            println!("帧 {worst} 相对第 0 帧转角最大的 12 根骨:");
            for (n, d) in ang.iter().take(12) {
                println!("  {n:32} {d:8.2}°");
            }
            let big = ang.iter().filter(|(_, d)| *d > 90.0).count();
            println!("转角 >90° 的骨：{big} 根 / {}", ang.len());
            // 结构判据：这些骨在骨架里的**下标**成不成段；再看索引表（MIN3 在 0xD2+74×骨、
            // MIN2 在 0xD2+90×骨，4B/骨）给它们的块号。
            let mut idxs: Vec<usize> = Vec::new();
            for (i, (n, d)) in ang.iter().enumerate() {
                if *d > 90.0 {
                    idxs.push(i);
                    let _ = n;
                }
            }
            if !idxs.is_empty() {
                let stride_tail = if min3 { 74 } else { 90 };
                let at = 0xd2 + h.bones.len() * stride_tail;
                let tbl: Vec<u32> = (0..h.bones.len())
                    .map(|j| {
                        araw.get(at + j * 4..at + j * 4 + 4)
                            .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
                            .unwrap_or(0)
                    })
                    .collect();
                let gaps: Vec<usize> = idxs.windows(2).map(|w| w[1] - w[0]).collect();
                let segs = 1 + gaps.iter().filter(|g| **g > 1).count();
                println!(
                    "  >90° 骨下标：最小 {} 最大 {} 跨度 {} · 分成 {segs} 段 · 相邻间隔中位 {:?}",
                    idxs[0],
                    idxs[idxs.len() - 1],
                    idxs[idxs.len() - 1] - idxs[0] + 1,
                    {
                        let mut g = gaps.clone();
                        g.sort_unstable();
                        g.get(g.len() / 2).copied()
                    }
                );
                println!(
                    "  前 10 根：{:?}",
                    idxs.iter()
                        .take(10)
                        .map(|j| format!("{}[#{} 表{}]", h.bones[*j].name, j, tbl[*j]))
                        .collect::<Vec<_>>()
                );
                let bad_tbl = idxs.iter().filter(|j| tbl[**j] > 0xFFFF_0000).count();
                println!("  其中索引表是哨兵（该骨没有块）的：{bad_tbl} 根");
            }
        }
    }
    // 逐帧最大位移跳变（按骨找）：飞出去的骨会把相机取景一起带歪。
    let mut per_frame_dp: Vec<(usize, f32, String)> = Vec::new();
    for f in 1..anim.frames {
        let mut best = (0f32, String::new());
        for t in &anim.tracks {
            if t.positions.len() <= f {
                continue;
            }
            let (p0, p1) = (t.positions[f - 1], t.positions[f]);
            let dp = ((p1[0] - p0[0]).powi(2) + (p1[1] - p0[1]).powi(2) + (p1[2] - p0[2]).powi(2)).sqrt();
            if dp > best.0 {
                best = (dp, t.bone.clone());
            }
        }
        per_frame_dp.push((f, best.0, best.1));
    }
    for (f, dp, b) in &per_frame_dp {
        println!("帧 {f:3}: 最大位移跳变 {dp:8.4}  ({b})");
    }

    let mut jumps: Vec<(String, f32, f32)> = Vec::new();
    for t in &anim.tracks {
        if t.bone.is_empty() || t.rotations.len() <= worst || worst == 0 {
            continue;
        }
        let q0 = t.rotations[worst - 1];
        let q1 = t.rotations[worst];
        let n0: f32 = q0.iter().map(|v| v * v).sum::<f32>().sqrt();
        let n1: f32 = q1.iter().map(|v| v * v).sum::<f32>().sqrt();
        let dp = {
            let (p0, p1) = (t.positions[worst - 1], t.positions[worst]);
            ((p1[0] - p0[0]).powi(2) + (p1[1] - p0[1]).powi(2) + (p1[2] - p0[2]).powi(2)).sqrt()
        };
        jumps.push((format!("{}(|q|{n0:.3}→{n1:.3})", t.bone), qangle(&q0, &q1), dp));
    }
    jumps.sort_by(|x, y| y.2.total_cmp(&x.2));
    println!("帧 {} 相对上一帧**位移**跳得最狠的 12 根骨（位移 / 旋转°）:", worst);
    for (n, ang, dp) in jumps.iter().take(12) {
        println!("  {n:40} {dp:9.4}  {ang:8.2}°");
    }
    jumps.sort_by(|x, y| y.1.total_cmp(&x.1));
    println!("帧 {} 相对上一帧**旋转**跳得最狠的 12 根骨（旋转° / 位移）:", worst);
    for (n, ang, dp) in jumps.iter().take(12) {
        println!("  {n:40} {ang:8.2}°  {dp:.4}");
    }
}
