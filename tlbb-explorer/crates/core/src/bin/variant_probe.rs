//! `variant_probe` — 变体记录（132B 那族）的矩阵语义探针。
//!
//! 为什么还要一个探针：主干 `parse_nodes` 故意不并变体记录，而它的语义一直靠一次性
//! 脚本比字节（`.scratch/cfg身份普查_20261011.md` 第二十四～二十九补）。那些脚本没留档、
//! 判据也和 Rust 那套共用判据（`name_field`/`affine_basis`）不是同一份代码——
//! 双实现分叉正是这个仓库撞过的坑。这里直接用主干的读法，数字不再来自第二套判据。
//!
//! 三个比对：
//! * `--same`：同一份文件里同名骨的 变体 vs 标准，比 本身 / 转置 / 逆 / 逆的转置 四个候选。
//! * `--12slot`：只比 12 个有效元素（前三行 × 前三列），排除齐次位与平移那 4 个约定槽。
//! * `--crosspart`：同一角色两个部件文件里，**变体对变体**（不是变体对标准）同骨比对——
//!   局部变换应当与部件无关，世界变换则会差一个根变换。
//!
//! 只读纪律：db 只读、pak 只读，什么都不写。
//!
//! 用法：
//! ```text
//! variant_probe [--root D:/TLGL] [--mode same|12slot|trans|axis|crosspart|rest|gain] 干名[,...]
//! variant_probe --mode=gain --batch=.mesh [--limit=N]     # 覆盖面批量（默认 400）
//! ```

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::rest;
use tlbb_core::preview::{bone_count, hierarchy_stuck, parse_ani, parse_hierarchy, parse_nodes, parse_nodes_variant, rest_poses, tail_inf_audit, tail_stuck_detail, tail_walk_steps, pose};

fn locate(con: &Connection, name: &str) -> Option<(u64, String)> {
    let mut stmt = con
        .prepare("SELECT hash, coalesce(pak,'') FROM resources WHERE path LIKE ?1 AND stored > 0 LIMIT 1")
        .ok()?;
    stmt.query_row([format!("%/{}", name.replace('\'', "''"))], |r| {
        let hex: String = r.get(0)?;
        let pak: String = r.get(1)?;
        Ok((hex, pak))
    })
    .ok()
    .and_then(|(hex, pak)| u64::from_str_radix(&hex, 16).ok().map(|h| (h, pak)))
}

/// 干名 → 实际文件名（部件名精确、组干名按前缀取最大的一份）。
fn resolve_mesh(con: &Connection, stem: &str) -> Option<String> {
    let base = |p: String| p.rsplit('/').next().unwrap_or("").to_string();
    let exact: Option<String> = con
        .prepare("SELECT coalesce(path,'') FROM resources WHERE ext='.mesh' AND path LIKE ?1 LIMIT 1")
        .ok()
        .and_then(|mut st| st.query_row([format!("%/{stem}.mesh")], |r| r.get(0)).ok());
    if let Some(p) = exact {
        return Some(base(p));
    }
    con.prepare("SELECT coalesce(path,'') FROM resources WHERE ext='.mesh' AND path LIKE ?1 ORDER BY stored DESC LIMIT 1")
        .ok()
        .and_then(|mut st| st.query_row([format!("%/{stem}%.mesh")], |r| r.get(0)).ok())
        .map(base)
}

/// 清单里一条资源的完整路径（按文件名结尾取第一条）。
fn path_of(con: &Connection, name: &str) -> Option<String> {
    let mut stmt = con
        .prepare("SELECT coalesce(path,'') FROM resources WHERE path LIKE ?1 LIMIT 1")
        .ok()?;
    stmt.query_row([format!("%/{}", name.replace('\'', "''"))], |r| r.get(0)).ok()
}

/// 一只模型的动作清单：同目录的 `<目录>/ani/*.ani`（与 `skel_dump` 同口径——
/// 客户端就是这么摆的，按模型干名捞会一条也捞不到）。
fn anim_names_for(con: &Connection, mesh_path: &str) -> Vec<String> {
    let dir = match mesh_path.rfind('/') {
        Some(i) => &mesh_path[..i],
        None => return Vec::new(),
    };
    let mut out = Vec::new();
    if let Ok(mut stmt) =
        con.prepare("SELECT coalesce(path,'') FROM resources WHERE ext='.ani' AND path LIKE ?1")
    {
        if let Ok(rows) = stmt.query_map([format!("%{dir}/ani/%")], |r| r.get::<_, String>(0)) {
            for p in rows.flatten() {
                if let Some(n) = p.rsplit('/').next() {
                    if !n.is_empty() && !out.contains(&n.to_string()) {
                        out.push(n.to_string());
                    }
                }
            }
        }
    }
    out.sort();
    out
}

/// 一批网格：按路径片段筛，`limit` 兜住别一次跑穿（同 `skel_dump` 的批量口径）。
fn mesh_paths(con: &Connection, prefix: &str, limit: usize) -> Vec<String> {
    let mut stmt = match con.prepare(
        "SELECT coalesce(path,'') FROM resources WHERE ext='.mesh' AND path LIKE ?1 \
         ORDER BY stored DESC LIMIT ?2",
    ) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };
    stmt.query_map(
        rusqlite::params![format!("%{prefix}%"), limit as i64],
        |r| r.get::<_, String>(0),
    )
    .map(|rows| rows.flatten().collect())
    .unwrap_or_default()
}

fn bytes_of(con: &Connection, root: &Path, paks: &mut BTreeMap<String, Pak>, name: &str) -> Option<Vec<u8>> {
    let (hash, pak) = locate(con, name)?;
    if !paks.contains_key(&pak) {
        paks.insert(pak.clone(), Pak::open(&root.join(format!("{pak}.pak"))).ok()?);
    }
    let p = paks.get(&pak)?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(p, &rec).ok().map(|d| d.bytes)
}

fn transposed(m: &[f32; 16]) -> [f32; 16] {
    let mut t = [0f32; 16];
    for r in 0..4 {
        for c in 0..4 {
            t[c * 4 + r] = m[r * 4 + c];
        }
    }
    t
}

/// 差值口径：逐元素绝对差的最大值（主序全 16 位，或只取前三行×前三列那 12 位）。
/// 无效（非有限/分母为 0）返回 `None`，不硬凑成一个数。
fn diff(a: &[f32; 16], b: &[f32; 16], slots: &[usize]) -> Option<f64> {
    let mut mx = 0f64;
    for &k in slots {
        let (x, y) = (a[k] as f64, b[k] as f64);
        if !x.is_finite() || !y.is_finite() {
            return None;
        }
        mx = mx.max((x - y).abs());
    }
    Some(mx)
}

fn slots16() -> Vec<usize> {
    (0..16).collect()
}

fn slots12() -> Vec<usize> {
    let mut v = Vec::new();
    for r in 0..3 {
        for c in 0..3 {
            v.push(r * 4 + c);
        }
    }
    v
}

fn main() {
    let mut root = PathBuf::from("D:/TLGL");
    let mut mode = "same".to_string();
    let mut ani_name: Option<String> = None;
    let mut batch = String::new();
    let mut limit: usize = 400;
    let mut names: Vec<String> = Vec::new();
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        if a == "--root" {
            root = PathBuf::from(args.next().unwrap_or_default());
        } else if a == "--ani" {
            ani_name = Some(args.next().unwrap_or_default());
        } else if let Some(v) = a.strip_prefix("--ani=") {
            ani_name = Some(v.to_string());
        } else if let Some(v) = a.strip_prefix("--mode=") {
            mode = v.to_string();
        } else if a == "--mode" {
            mode = args.next().unwrap_or_default();
        } else if let Some(v) = a.strip_prefix("--batch=") {
            batch = v.to_string();
        } else if let Some(v) = a.strip_prefix("--limit=") {
            limit = v.parse().unwrap_or(400);
        } else if let Some(v) = a.strip_prefix("--names=") {
            names = v.split(',').map(|s| s.trim().to_string()).collect();
        } else if !a.starts_with("--") {
            names = a.split(',').map(|s| s.trim().to_string()).collect();
        } else {
            eprintln!("未知参数 {a}");
        }
    }
    if names.is_empty()
        && !matches!(mode.as_str(), "gain" | "missnames" | "skin" | "shiftcensus" | "mirr" | "localcensus" | "stdcensus" | "chaingap" | "whychain" | "chaincluster" | "whyerr" | "whytail" | "steps")
    {
        eprintln!("用法：variant_probe [--root DIR] [--mode same|12slot|trans|axis|crosspart|rest|gain|missnames|skin|local|shift|shiftcensus|mirr|pose|xstd|localcensus|stdcensus] 干名[,...]");
        eprintln!("      批量：variant_probe --mode=gain|missnames|skin|shiftcensus|whytail --batch=路径片段 [--limit=N]");
        std::process::exit(2);
    }
    let db = root.join(".scratch/resources.db");
    let con = match Connection::open_with_flags(
        &db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    ) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("资源清单打不开（{db:?}）：{e}");
            std::process::exit(2);
        }
    };
    let mut paks: BTreeMap<String, Pak> = BTreeMap::new();

    if mode == "gain" {
        // 全库（或一片）覆盖面：变体块到底在多少份网格里存在、能补多少「标准扫描认不到的骨名」。
        // 只出数、不改主干——`parse_nodes` 该不该并它仍由语义定下来之后再说。
        let paths = mesh_paths(&con, &batch, limit);
        println!("# file\tdeclared\tstd\tvar\tonly\tonChain\tchainLen\tcoveredAfterMerge\taniBones\tinAni");
        let (mut files, mut with_var, mut only_all, mut chain_all, mut reach) = (0usize, 0usize, 0usize, 0usize, 0usize);
        let (mut ani_names_all, mut ani_in_all, mut with_ani) = (0usize, 0usize, 0usize);
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            files += 1;
            let std_nodes = parse_nodes(&raw);
            let var = parse_nodes_variant(&raw);
            if var.is_empty() {
                continue;
            }
            with_var += 1;
            let std_names: Vec<&str> = std_nodes.iter().map(|n| n.name.as_str()).collect();
            let chain: Vec<String> = parse_hierarchy(&raw)
                .map(|h| h.bones.iter().map(|b| b.name.clone()).collect())
                .unwrap_or_default();
            let mut only_names: Vec<&str> = var
                .iter()
                .map(|v| v.name.as_str())
                .filter(|n| !std_names.contains(n))
                .collect();
            let only = only_names.len();
            let on_chain = only_names.iter().filter(|n| chain.iter().any(|c| c == *n)).count();
            // 另一份容器：同目录 `ani/` 里第一个解得开的 `.ani`，它的骨名表（轨道名 + 静态区名）
            // 与 `.mesh` 无关，是**真独立**的旁证口径。
            let mut ani_bones = 0usize;
            let mut in_ani = 0usize;
            let mut ani_file = String::new();
            for a in anim_names_for(&con, p) {
                let Some(araw) = bytes_of(&con, &root, &mut paks, &a) else { continue };
                let Some(an) = parse_ani(&araw) else { continue };
                let mut bones: Vec<String> = an.tracks.iter().map(|t| t.bone.clone()).collect();
                if let Some(rs) = rest_poses(&araw) {
                    for r in rs {
                        if !r.bone.is_empty() && !bones.contains(&r.bone) {
                            bones.push(r.bone);
                        }
                    }
                }
                ani_bones = bones.len();
                in_ani = only_names.iter().filter(|n| bones.iter().any(|b| b == *n)).count();
                ani_file = a;
                break;
            }
            only_names.sort();
            only_all += only;
            chain_all += on_chain;
            ani_in_all += in_ani;
            if ani_bones > 0 {
                with_ani += 1;
                ani_names_all += only;
            }
            let declared = bone_count(&raw).unwrap_or(0);
            if declared > 0 && std_nodes.len() + only >= declared {
                reach += 1;
            }
            println!(
                "{name}\t{declared}\t{}\t{}\t{only}\t{on_chain}\t{}\t{}\t{ani_bones}\t{in_ani}",
                std_nodes.len(),
                var.len(),
                chain.len(),
                std_nodes.len() + only
            );
        }
        println!(
            "\n# 筛出 {} 份 · 读到 {} 份 · 带变体记录 {with_var} 份 · 变体独有骨名合计 {only_all}（其中 {chain_all} 个在该份父骨链上）· 两套合起来够到声明骨数的 {reach} 份 · 同目录有 .ani 可比 {with_ani} 份（那份里独有 {ani_names_all} 个，也在 .ani 骨名表里的 {ani_in_all} 个）",
            paths.len(),
            files
        );
        return;
    }

    struct Load {
        file: String,
        std_nodes: Vec<tlbb_core::preview::Node>,
        var_nodes: Vec<tlbb_core::preview::Node>,
        declared: Option<usize>,
    }
    let mut loaded: Vec<Load> = Vec::new();
    for stem in &names {
        let Some(mesh) = resolve_mesh(&con, stem.trim_end_matches(".mesh")) else {
            println!("  跳过 {stem}：清单里找不到同名/前缀 .mesh");
            continue;
        };
        let Some(raw) = bytes_of(&con, &root, &mut paks, &mesh) else {
            println!("  跳过 {stem}：读不出字节");
            continue;
        };
        loaded.push(Load {
            file: mesh,
            std_nodes: parse_nodes(&raw),
            var_nodes: parse_nodes_variant(&raw),
            declared: bone_count(&raw),
        });
    }
    if loaded.is_empty()
        && !matches!(mode.as_str(), "gain" | "missnames" | "skin" | "shiftcensus" | "mirr" | "localcensus" | "stdcensus" | "chaingap" | "whychain" | "chaincluster" | "whyerr" | "whytail" | "steps")
    {
        eprintln!("一份都没读到");
        std::process::exit(2);
    }

    let slots = if mode == "12slot" { slots12() } else { slots16() };
    let tag = if mode == "12slot" { "12位差" } else { "16位差" };

    if mode == "trans" {
        // 基向量已经实测能整体精确相等（12 位差 0.0000），剩下的差别全在平移那三个数。
        // 这一档就只问一件事：变体记录的平移行 = 标准记录的什么？
        // 候选：存储末行（= 逆矩阵的平移）/ 求逆后的末行（= 真实骨位）/ 转置矩阵的末列。
        for ld in &loaded {
            println!("\n{} · 标准 {} 条 · 变体 {} 条", ld.file, ld.std_nodes.len(), ld.var_nodes.len());
            for n in &ld.var_nodes {
                let Some(s) = ld.std_nodes.iter().find(|m| m.name == n.name) else { continue };
                let vt = [n.bind[12], n.bind[13], n.bind[14]];
                let mut cands: Vec<(&str, [f32; 3])> = vec![("存储末行", [s.bind[12], s.bind[13], s.bind[14]])];
                if let Some(inv) = pose::mat_inverse_affine(&s.bind) {
                    cands.push(("求逆末行(真实骨位)", [inv[12], inv[13], inv[14]]));
                }
                let t = transposed(&s.bind);
                cands.push(("转置末行", [t[12], t[13], t[14]]));
                let basis_ok = slots12().iter().all(|&k| (n.bind[k] - s.bind[k]).abs() <= 1e-6);
                let parts: Vec<String> = cands
                    .iter()
                    .map(|(label, c)| {
                        let d = (0..3).map(|k| (vt[k] as f64 - c[k] as f64).abs()).fold(0f64, f64::max);
                        format!("{label} {d:.6}")
                    })
                    .collect();
                println!(
                    "  {:<24} 基向量{} 平移 {:?} 标准末行 {:?} → {}",
                    n.name,
                    if basis_ok { "等" } else { "不等" },
                    vt,
                    [s.bind[12], s.bind[13], s.bind[14]],
                    parts.join(" · ")
                );
            }
        }
        return;
    }

    if mode == "axis" {
        // 基向量逐元素相等、只有平移差 0.006~0.16 的那批：差向量到底朝哪儿？
        // 若它平行于三条基向量之一（|cos|≈1），就是「沿骨自身轴的局部偏移」；
        // 若三条都不平行，它是世界系的某个平移，语义另说。
        for ld in &loaded {
            println!("\n{} · 变体 {} 条", ld.file, ld.var_nodes.len());
            let mut par = 0usize;
            let mut tot = 0usize;
            for n in &ld.var_nodes {
                let Some(s) = ld.std_nodes.iter().find(|m| m.name == n.name) else { continue };
                if !slots12().iter().all(|&k| (n.bind[k] - s.bind[k]).abs() <= 1e-6) {
                    continue;
                }
                let d: [f64; 3] =
                    (0..3).map(|k| n.bind[12 + k] as f64 - s.bind[12 + k] as f64).collect::<Vec<_>>().try_into().unwrap();
                let len = (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt();
                if len < 1e-9 {
                    continue;
                }
                tot += 1;
                let cos: Vec<f64> = (0..3)
                    .map(|r| {
                        let row: [f64; 3] =
                            (0..3).map(|c| s.bind[r * 4 + c] as f64).collect::<Vec<_>>().try_into().unwrap();
                        let rl = (row[0] * row[0] + row[1] * row[1] + row[2] * row[2]).sqrt();
                        let dot = d[0] * row[0] + d[1] * row[1] + d[2] * row[2];
                        (dot / (rl * len)).abs()
                    })
                    .collect();
                let (bk, bv) = cos
                    .iter()
                    .enumerate()
                    .fold((0usize, 0f64), |(ai, av), (i, v)| if *v > av { (i, *v) } else { (ai, av) });
                if bv > 0.999 {
                    par += 1;
                }
                println!(
                    "  {:<22} |差| {:.6} 平行度 行{} |cos|={:.6} 其余 {:.4} {:.4}",
                    n.name, len, bk, bv, cos[(bk + 1) % 3], cos[(bk + 2) % 3]
                );
            }
            println!("  基向量相等且可量的 {tot} 根：差向量平行于某条基向量的 {par} 根");
        }
        return;
    }


    if mode == "rest" {
        // 变体块既然与部件无关，就对着**骨架级**的另一处数据比：`.ani` 静态区。
        // 已知语义（`preview::rest` 模块头，研究班 2026-10-07 钉死）：
        //   静态区 +12 四元数 qrest = bind **局部**旋转的逆，行向量口径下局部旋转 = quat_to_mat_passive(qrest)；
        //   轨道常量平移（每骨 positions 逐分量中位数）= bind 局部平移。
        // 所以这里问两件事：变体的基向量 = 局部旋转？变体的平移 = 静态区 offset / 轨道常量？
        let Some(ani) = &ani_name else {
            eprintln!("--mode=rest 要配 --ani=名字.ani");
            std::process::exit(2);
        };
        let mesh = &loaded[0];
        let raw = match bytes_of(&con, &root, &mut paks, ani) {
            Some(r) => r,
            None => {
                eprintln!("读不出 {ani}");
                std::process::exit(2);
            }
        };
        let rests = parse_ani(&raw).and_then(|_| rest_poses(&raw)).unwrap_or_default();
        let tracks = parse_ani(&raw).map(|a| a.tracks).unwrap_or_default();
        let median = |t: &tlbb_core::preview::Track| -> [f32; 3] {
            let mut out = [0f32; 3];
            for k in 0..3 {
                let mut col: Vec<f32> = t.positions.iter().map(|p| p[k]).collect();
                col.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
                out[k] = col[col.len() / 2];
            }
            out
        };
        println!(
            "\n{} · 变体 {} 条 · 静态区 {} 条 · 轨道 {} 条",
            mesh.file,
            mesh.var_nodes.len(),
            rests.len(),
            tracks.len()
        );
        let mut hits_rot = 0usize;
        let mut hits_med = 0usize;
        let mut hits_off = 0usize;
        let mut cmp = 0usize;
        for v in &mesh.var_nodes {
            let Some(r) = rests.iter().find(|r| r.bone == v.name) else { continue };
            let lmat = rest::quat_to_mat_passive(&r.rotation);
            let drot = diff(&v.bind, &lmat, &slots12());
            let t = tracks.iter().find(|t| t.bone == v.name).map(&median);
            let vt = [v.bind[12], v.bind[13], v.bind[14]];
            let dmed = t.map(|m| (0..3).map(|k| (vt[k] as f64 - m[k] as f64).abs()).fold(0f64, f64::max));
            let doff = (0..3)
                .map(|k| (vt[k] as f64 - r.offset[k] as f64).abs())
                .fold(0f64, f64::max);
            cmp += 1;
            if drot.map_or(false, |d| d <= 1e-4) {
                hits_rot += 1;
            }
            if dmed.map_or(false, |d| d <= 1e-3) {
                hits_med += 1;
            }
            if doff <= 1e-3 {
                hits_off += 1;
            }
            println!(
                "  {:<24} 局部旋转差 {}  轨道常量差 {}  静态区offset差 {:.6}",
                v.name,
                drot.map_or("—".to_string(), |d| format!("{d:.6}")),
                dmed.map_or("无轨道".to_string(), |d| format!("{d:.6}")),
                doff
            );
        }
        println!(
            "\n可比的 {cmp} 根：基向量=局部旋转(≤1e-4) {hits_rot} · 平移=轨道常量(≤1e-3) {hits_med} · 平移=静态区offset {hits_off}"
        );
        return;
    }

    if mode == "skin" {
        // 变体记录**带不带影响顶点表**、带上又能多覆盖多少顶点。
        // 只出数、不改主干：口径与 `tree_check` 那份「带表 2,227/7,996」可比
        // （同一份里先收标准记录的顶点集，再看变体那套往里新增了多少个）。
        use std::collections::HashSet;
        let paths = mesh_paths(&con, &batch, limit);
        let (mut files, mut with_var, mut var_recs, mut var_skin) = (0usize, 0usize, 0usize, 0usize);
        let (mut new_verts, mut files_gain, mut std_verts) = (0usize, 0usize, 0usize);
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            files += 1;
            let var = parse_nodes_variant(&raw);
            if var.is_empty() {
                continue;
            }
            with_var += 1;
            var_recs += var.len();
            let mut covered: HashSet<u32> = HashSet::new();
            for n in parse_nodes(&raw) {
                if let Some(sk) = &n.skin {
                    covered.extend(sk.vertices.iter().copied());
                }
            }
            let before = covered.len();
            std_verts += before;
            for n in &var {
                if let Some(sk) = &n.skin {
                    var_skin += 1;
                    covered.extend(sk.vertices.iter().copied());
                }
            }
            let added = covered.len() - before;
            if added > 0 {
                files_gain += 1;
                new_verts += added;
            }
        }
        println!(
            "# 读到 {files} 份 · 带变体记录 {with_var} 份（变体记录 {var_recs} 条，其中带影响表 {var_skin} 条）\n\
             # 标准那套覆盖的顶点合计 {std_verts} · 变体再往里新增 {new_verts} 个（有增益的份数 {files_gain}）"
        );
        return;
    }

    if mode == "local" {
        // 没被验过的候选：变体 = **由标准记录自己推出的局部变换**
        // （行向量口径 `W_child = L · W_parent` ⇒ `L = W_child · inv(W_parent)`，
        //  而存储值是世界的逆，所以 `W = inv(stored)`）。
        // 之前只拿它比过 `.ani` 的 frame0（第二十七补否掉），没比过网格侧的父链。
        fn mul(a: &[f32; 16], b: &[f32; 16]) -> [f32; 16] {
            let mut o = [0f32; 16];
            for r in 0..4 {
                for c in 0..4 {
                    let mut s = 0f32;
                    for k in 0..4 {
                        s += a[r * 4 + k] * b[k * 4 + c];
                    }
                    o[r * 4 + c] = s;
                }
            }
            o
        }
        for ld in &loaded {
            let raw = match bytes_of(&con, &root, &mut paks, &ld.file) {
                Some(r) => r,
                None => continue,
            };
            let h = match parse_hierarchy(&raw) {
                Some(h) => h,
                None => {
                    println!("\n{} · 父骨链解不出，这条比不了", ld.file);
                    continue;
                }
            };
            println!("\n{} · 标准 {} 条 · 变体 {} 条 · 链 {} 根", ld.file, ld.std_nodes.len(), ld.var_nodes.len(), h.bones.len());
            let bind_of = |nm: &str| ld.std_nodes.iter().find(|n| n.name == nm).map(|n| n.bind);
            let (mut eq, mut ne, mut skip) = (0usize, 0usize, 0usize);
            let mut least = f64::MAX;
            for bi in 0..h.bones.len() {
                let nm = h.bones[bi].name.clone();
                let Some(pi) = h.bones[bi].parent else { continue };
                let pname = h.bones[pi].name.clone();
                let Some(v) = ld.var_nodes.iter().find(|x| x.name == nm) else { continue };
                let (Some(wc), Some(wp)) = (bind_of(&nm), bind_of(&pname)) else { skip += 1; continue };
                // W = inv(stored)；L = W_child · inv(W_parent)
                let (Some(w_c), Some(w_p)) = (pose::mat_inverse_affine(&wc), pose::mat_inverse_affine(&wp)) else { skip += 1; continue };
                let l = mul(&w_c, &w_p);
                match diff(&v.bind, &l, &slots16()) {
                    Some(dv) => {
                        if dv < least {
                            least = dv;
                        }
                        if dv <= 1e-4 {
                            eq += 1;
                        } else {
                            ne += 1;
                        }
                        println!("  {nm:<24} 与局部差 {dv:.6} {}", if dv <= 1e-4 { "对上" } else { "不对上" });
                    }
                    None => println!("  {nm:<24} 差值无效（非有限）"),
                }
            }
            println!(
                "  可比：对上 {eq} · 不对上 {ne} · 缺记录跳过 {skip} · 最小差 {}",
                if least == f64::MAX { "无可比".to_string() } else { format!("{least:.6}") }
            );
        }
        return;
    }

    if mode == "shift" {
        // 第三十补留下的一条正面线索没追完：有些变体记录的**基向量与标准整块精确相等**，
        // 只有平移那三个数差 0.006~0.16。这个差若在一份内**恒定**，它就是「整份的一个根变换」，
        // 语义当场可定；若不恒定，那这些记录只是各自不同的姿态。
        for ld in &loaded {
            let mut ds: Vec<([f64; 3], String)> = Vec::new();
            for v in &ld.var_nodes {
                let Some(s) = ld.std_nodes.iter().find(|m| m.name == v.name) else { continue };
                if !slots12().iter().all(|&k| (v.bind[k] - s.bind[k]).abs() <= 1e-6) {
                    continue;
                }
                let d = [
                    v.bind[12] as f64 - s.bind[12] as f64,
                    v.bind[13] as f64 - s.bind[13] as f64,
                    v.bind[14] as f64 - s.bind[14] as f64,
                ];
                ds.push((d, v.name.clone()));
            }
            println!("\n{} · 基向量相等的 {} 根", ld.file, ds.len());
            if ds.len() < 2 {
                println!("  不足两根，判不了恒不恒定");
                continue;
            }
            for (d, nm) in &ds {
                println!("  {nm:<24} 差 [{:>10.6}, {:>10.6}, {:>10.6}]", d[0], d[1], d[2]);
            }
            let mut axis_spread = [0f64; 3];
            for k in 0..3 {
                let col: Vec<f64> = ds.iter().map(|(d, _)| d[k]).collect();
                let mn = col.iter().fold(f64::INFINITY, |a, &b| a.min(b));
                let mx = col.iter().fold(f64::NEG_INFINITY, |a, &b| a.max(b));
                axis_spread[k] = mx - mn;
            }
            println!(
                "  逐轴极差 [{:.6}, {:.6}, {:.6}] · 恒定判据（极差 ≤1e-4）：{}",
                axis_spread[0],
                axis_spread[1],
                axis_spread[2],
                if axis_spread.iter().all(|s| *s <= 1e-4) { "恒定" } else { "不恒定" }
            );
            // 参照：该份根骨（标准记录里名字最短的那条通常就是 `000`/`origin`）的存储平移
            if let Some(r) = ld
                .std_nodes
                .iter()
                .min_by_key(|n| n.name.chars().count())
            {
                println!(
                    "  参照 · 根 {} 存储平移 [{:.6}, {:.6}, {:.6}]",
                    r.name, r.bind[12], r.bind[13], r.bind[14]
                );
            }
        }
        return;
    }



    if mode == "shiftcensus" {
        // 第四十一补那条判据只有 `rongyanjushou_b0` 一份支撑。这里铺到全库：
        // 每份挑「基向量与标准整块精确相等」的变体记录，量平移差的逐轴极差，
        // 统计恒定与否、以及极差最大的是哪条轴（上一份看到的是「几乎只压 X」）。
        let paths = mesh_paths(&con, &batch, limit);
        let (mut files, mut with_var, mut testable, mut constant, mut varying) =
            (0usize, 0usize, 0usize, 0usize, 0usize);
        let mut axis_max = [0usize; 3];
        let mut bones = 0usize;
        // 第四十二补留的第①件：左右镜像对的差值是不是「同一条轴反号」。
        // 全库口径：同一份里 `x_l_foo` 与 `x_r_foo` 都有可比记录时，比它们三个分量的关系。
        let mut pairs = 0usize;
        let mut p_x_flip = 0usize; // X 反号、Y/Z 同
        let mut p_y_flip = 0usize; // Y 反号、X/Z 同
        let mut p_z_flip = 0usize; // Z 反号、X/Y 同
        let mut p_same = 0usize; // 三个都同
        let mut p_other = 0usize;
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            files += 1;
            let var = parse_nodes_variant(&raw);
            if var.is_empty() {
                continue;
            }
            with_var += 1;
            let std_nodes = parse_nodes(&raw);
            let mut ds: Vec<(String, [f64; 3])> = Vec::new();
            for v in &var {
                let Some(s) = std_nodes.iter().find(|m| m.name == v.name) else { continue };
                if !slots12().iter().all(|&k| (v.bind[k] - s.bind[k]).abs() <= 1e-6) {
                    continue;
                }
                let d = [
                    v.bind[12] as f64 - s.bind[12] as f64,
                    v.bind[13] as f64 - s.bind[13] as f64,
                    v.bind[14] as f64 - s.bind[14] as f64,
                ];
                ds.push((v.name.clone(), d));
            }
            if ds.len() < 2 {
                continue;
            }
            testable += 1;
            bones += ds.len();
            let mut spread = [0f64; 3];
            for k in 0..3 {
                let col: Vec<f64> = ds.iter().map(|(_, d)| d[k]).collect();
                let mn = col.iter().fold(f64::INFINITY, |a, &b| a.min(b));
                let mx = col.iter().fold(f64::NEG_INFINITY, |a, &b| a.max(b));
                spread[k] = mx - mn;
            }
            // 镜像对：同一份里 `_l_` 与 `_r_` 都有可比记录时才比，容差 1e-4
            for (nm, a) in &ds {
                let Some(rest) = nm.find("_l_") else { continue };
                let mut mir = nm.clone();
                mir.replace_range(rest..rest + 3, "_r_");
                let Some((_, b)) = ds.iter().find(|(m, _)| m == &mir) else { continue };
                let eq = |i: usize| (a[i] - b[i]).abs() <= 1e-4;
                // 零对零时 `|a-b|<=tol` 与 `|a+b|<=tol` 同时成立，所以「反号」必须先看量级：
                // 两边都是零头就不叫反号，归「都同」（第四十三补就是撞在这上面的）。
                let big = |i: usize| a[i].abs().max(b[i].abs()) > 1e-4;
                let flip = |i: usize| big(i) && (a[i] + b[i]).abs() <= 1e-4;
                pairs += 1;
                if flip(0) && eq(1) && eq(2) {
                    p_x_flip += 1;
                } else if eq(0) && flip(1) && eq(2) {
                    p_y_flip += 1;
                } else if eq(0) && eq(1) && flip(2) {
                    p_z_flip += 1;
                } else if eq(0) && eq(1) && eq(2) {
                    p_same += 1;
                } else {
                    p_other += 1;
                }
            }
            if spread.iter().all(|s| *s <= 1e-4) {
                constant += 1;
            } else {
                varying += 1;
                let am = (0..3).reduce(|acc, k| if spread[k] > spread[acc] { k } else { acc }).unwrap();
                axis_max[am] += 1;
                println!("{name}\t{}\t{:.6}\t{:.6}\t{:.6}", ds.len(), spread[0], spread[1], spread[2]);
            }
        }
        println!(
            "\n# 读到 {files} 份 · 带变体记录 {with_var} 份 · 可比（≥2 根基向量相等）{testable} 份、骨数合计 {bones}\n\
             # 平移差恒定（三轴极差 ≤1e-4）的份数 {constant} · 不恒定 {varying}\n\
             # 不恒定那些份里，极差最大的轴：X {} · Y {} · Z {}\n\
             # 镜像对 {pairs} 组：X 反号 {p_x_flip} · Y 反号 {p_y_flip} · Z 反号 {p_z_flip} · 三分量都同 {p_same} · 其余形态 {p_other}",
            axis_max[0], axis_max[1], axis_max[2]
        );
        return;
    }


    if mode == "stdcensus" {
        // 总表 #1~#4 当时只有 3 份文件、46 个同名对比，而 #1 后来在全库跑出过「只差 1~4 个 ULP」的相等
        // ⇒ 这四行的小样本结论必须铺成全库。口径同 `same`：变体记录 vs **同份**标准记录，
        // 四个候选（本身 / 转置 / 逆 / 逆的转置），命中阈值 ≤1e-6；#1 再按量级分桶。
        fn transposed(m: &[f32; 16]) -> [f32; 16] {
            let mut t = [0f32; 16];
            for r in 0..4 {
                for c in 0..4 {
                    t[c * 4 + r] = m[r * 4 + c];
                }
            }
            t
        }
        let paths = mesh_paths(&con, &batch, limit);
        let (mut files, mut cmpd) = (0usize, 0usize);
        let (mut h_self, mut h_t, mut h_i, mut h_it) = (0usize, 0usize, 0usize, 0usize);
        let (mut b_1e6, mut b_1e4, mut b_1e2, mut b_1e1) = (0usize, 0usize, 0usize, 0usize);
        let mut best: Option<f64> = None;
        let mut best_at = String::new();
        let mut id_hits: Option<usize> = None;
        // 55 补那条窄规则的**真实体量**：命中的那些骨，变体表覆盖多少顶点、
        // 其中有多少是该份标准那套没覆盖到的（骨数不等于顶点数，决策要的是后者）。
        let mut narrow_bones = 0usize;
        let mut narrow_verts_new = 0usize;
        let mut narrow_files = 0usize;
        let mut narrow_seen: Vec<String> = Vec::new();
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            files += 1;
            let var = parse_nodes_variant(&raw);
            if var.is_empty() {
                continue;
            }
            let stdn = parse_nodes(&raw);
            let mut std_cov: std::collections::HashSet<u32> = std::collections::HashSet::new();
            for nd in &stdn {
                if let Some(sk) = &nd.skin {
                    std_cov.extend(sk.vertices.iter().copied());
                }
            }
            for v in &var {
                let Some(s) = stdn.iter().find(|x| x.name == v.name) else { continue };
                cmpd += 1;
                let inv = pose::mat_inverse_affine(&s.bind);
                for (which, cand) in [
                    (0usize, Some(s.bind)),
                    (1, Some(transposed(&s.bind))),
                    (2, inv),
                    (3, inv.map(|m| transposed(&m))),
                ] {
                    let d = match cand.and_then(|c| diff(&v.bind, &c, &slots16())) {
                        Some(d) => d,
                        None => continue,
                    };
                    if d <= 1e-6 {
                        // 单位阵的四种候选重合（I⁻¹ = Iᵀ = I），命中不带信息 ⇒ 拆开数。
                        let is_id = |m: &[f32; 16]| {
                            (0..16).all(|k| {
                                let want = if k % 5 == 0 { 1.0 } else { 0.0 };
                                (m[k] - want).abs() <= 1e-6
                            })
                        };
                        let id_std = is_id(&s.bind);
                        if id_std {
                            *id_hits.get_or_insert(0) += 1;
                        } else {
                            match which {
                                0 => h_self += 1,
                                1 => h_t += 1,
                                2 => h_i += 1,
                                _ => h_it += 1,
                            }
                            // 54 补留的尾巴：命中到底是哪些文件哪些骨，逐条点名（命中是个位数到几十，明细不会淹）
                            if which == 0 {
                                // 窄规则体量：标准那条没表、变体这条有表 ⇒ 表能白捡多少顶点
                                if s.skin.is_none() {
                                    if let Some(sk) = &v.skin {
                                        narrow_bones += 1;
                                        for &vv in &sk.vertices {
                                            if std_cov.insert(vv) {
                                                narrow_verts_new += 1;
                                            }
                                        }
                                        if !narrow_seen.contains(&name) {
                                            narrow_seen.push(name.clone());
                                        }
                                    }
                                }
                                println!("  命中 {name} · {} 差 {d:.3e} · 标准记录基向量长度 {}{}{}",
                                    v.name,
                                    format!("{:.4}", (s.bind[0] * s.bind[0] + s.bind[1] * s.bind[1] + s.bind[2] * s.bind[2]).sqrt()),
                                    if s.skin.is_some() { " · 标准带表" } else { " · 标准无表" },
                                    if v.skin.is_some() { " · 变体带表" } else { " · 变体无表" });
                            }
                        }
                    }
                    if which == 0 {
                        if d <= 1e-6 {
                            b_1e6 += 1;
                        } else if d <= 1e-4 {
                            b_1e4 += 1;
                        } else if d <= 1e-2 {
                            b_1e2 += 1;
                        } else if d <= 1e-1 {
                            b_1e1 += 1;
                        }
                        if best.map_or(true, |x| d < x) {
                            best = Some(d);
                            best_at = format!("{name} · {}", v.name);
                        }
                    }
                }
            }
        }
        println!(
            "\n# 读到 {files} 份 · 同份同名可比 {cmpd} 根（总表 #1~#4 的全库人口）\n\
             # **剔除标准记录是单位阵之后**，≤1e-6 命中：本身 {h_self} · 转置 {h_t} · 逆 {h_i} · 逆的转置 {h_it}\n\
             # 单位阵命中（无信息，四种候选天然重合）：{} 个\n\
             # 「本身」这条按量级分桶（含单位阵）：≤1e-6 {b_1e6} · ≤1e-4 {b_1e4} · ≤1e-2 {b_1e2} · ≤1e-1 {b_1e1}\n\
             # 「本身」最接近的一根：{}（{best_at}）\n\
             # 窄规则体量（命中里「标准无表 + 变体带表」那一档）：骨 {narrow_bones} · 文件 {} · 白捡顶点 {narrow_verts_new}",
            id_hits.unwrap_or(0),
            best.map_or("无可比".to_string(), |d| format!("{d:.3e}")),
            narrow_seen.len()
        );
        return;
    }


    if mode == "whychain" {
        // 58 补那 246 份为什么建不出树——只问主干自己（`hierarchy_stuck` 就是它的诊断口），
        // 不另造第二套判据。取前 N 份「有记录但链为零」的份，把它卡在哪一步原样打出来。
        use tlbb_core::preview::hierarchy_stuck;
        let paths = mesh_paths(&con, &batch, limit);
        let mut shown = 0usize;
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            if parse_nodes(&raw).is_empty() {
                continue;
            }
            if parse_hierarchy(&raw).is_some() {
                continue;
            }
            shown += 1;
            if shown > 9999 {
                break;
            }
            let stdn = parse_nodes(&raw);
            println!(
                "\n{name} · 标准 {} 条 · 声明 {} 根 · 顶点 {}",
                stdn.len(),
                bone_count(&raw).unwrap_or(0),
                u32::from_le_bytes(raw[0x8C..0x90].try_into().unwrap_or([0; 4]))
            );
            println!("  主干诊断：{}", match hierarchy_stuck(&raw) { Some(s) => format!("{s:?}"), None => "hierarchy_stuck 返回 None（连诊断都给不出）".to_string() });
        }
        println!("\n# 本次取样里「有记录但建不出树」点了 {shown} 份");
        return;
    }


    if mode == "chaincluster" {
        // 61 补的结论：246 份的断点形状**不止一种**，所以先聚类再谈成因。
        // 指纹 = (eaten, declared, 卡点起 4 个 u32)；同指纹的份数与例子逐类打出来。
        use std::collections::BTreeMap;
        let paths = mesh_paths(&con, &batch, limit);
        let mut groups: BTreeMap<(usize, usize, [u32; 4]), (usize, String)> = BTreeMap::new();
        let mut gap = 0usize;
        let mut nostuck = 0usize;
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            if parse_nodes(&raw).is_empty() || parse_hierarchy(&raw).is_some() {
                continue;
            }
            gap += 1;
            let Some(sp) = hierarchy_stuck(&raw) else {
                nostuck += 1;
                continue;
            };
            let mut w = [0u32; 4];
            for k in 0..4 {
                if let Some(s) = raw.get(sp.stopped + 4 * k..sp.stopped + 4 * k + 4) {
                    w[k] = u32::from_le_bytes(s.try_into().unwrap_or([0; 4]));
                }
            }
            let e = groups.entry((sp.eaten, sp.declared, w)).or_insert((0, name.clone()));
            e.0 += 1;
        }
        println!("# 有记录但链为零的 {gap} 份 · 其中连诊断都给不出的 {nostuck} 份");
        let mut rows: Vec<_> = groups.into_iter().collect();
        rows.sort_by(|a, b| b.1 .0.cmp(&a.1 .0));
        println!("# 指纹（eaten, declared, 卡点起 4 个 u32）· 份数 · 一例");
        for (k, (n, ex)) in rows.iter().take(15) {
            println!("  {k:?} · {n} 份 · {ex}");
        }
        println!("# 不同指纹共 {} 种（前 15 种列出，长尾未逐条打）", rows.len());
        return;
    }


    if mode == "whyerr" {
        // 65 补留的最短一步：`hierarchy_forest` 返回 `Result<_, &'static str>`，
        // 那句人话就是主干自己对「为什么建不出树」的回答——把它按消息聚类，别再猜形状。
        use std::collections::BTreeMap;
        use tlbb_core::preview::hierarchy_forest;
        let paths = mesh_paths(&con, &batch, limit);
        let mut by_msg: BTreeMap<&'static str, (usize, String)> = BTreeMap::new();
        let mut files = 0usize;
        let mut ok = 0usize;
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            if parse_nodes(&raw).is_empty() || parse_hierarchy(&raw).is_some() {
                continue;
            }
            files += 1;
            match hierarchy_forest(&raw) {
                Ok(h) => {
                    ok += 1;
                    let e = by_msg.entry("（forest 能建，只是不多根）").or_insert((0, name.clone()));
                    e.0 += 1;
                    let _ = h;
                }
                Err(msg) => {
                    let e = by_msg.entry(msg).or_insert((0, name.clone()));
                    e.0 += 1;
                }
            }
        }
        println!("# 有记录但 parse_hierarchy 为零的 {files} 份 · 其中 forest 能建的 {ok} 份");
        let mut rows: Vec<_> = by_msg.into_iter().collect();
        rows.sort_by(|a, b| b.1 .0.cmp(&a.1 .0));
        println!("# 主干自己给的人话（按份数）：");
        for (msg, (n, ex)) in &rows {
            println!("  {n:>5} 份 · {msg} · 例 {ex}");
        }
        return;
    }


    if mode == "roots" {
        // 64 补那个嫌疑的最后一步：`tubalu` 那类走完条目却建不出树，是不是**多根并列**？
        // `parse_hierarchy` 要求恰好单根，而 `parse_forest` 放开这一条 ⇒ 两份都调，再数根。
        use tlbb_core::preview::{parse_forest, root_count};
        for ld in &loaded {
            let Some(raw) = bytes_of(&con, &root, &mut paks, &ld.file) else { continue };
            let n_root = root_count(&raw);
            let forest = parse_forest(&raw).map(|h| h.bones.len());
            println!(
                "  {} · 标准 {} 条 · parse_hierarchy {} · parse_forest {} · root_count {:?}",
                ld.file,
                ld.std_nodes.len(),
                if parse_hierarchy(&raw).is_some() { "成树" } else { "None" },
                forest.map_or("None".to_string(), |n| format!("{n} 根节点")),
                n_root
            );
        }
        return;
    }

    if mode == "steps" {
        // 98 补的正确做法：轨迹挂在**主干那一条走法**上（`tail_walk_steps` 调的就是
        // `tail_walk_traced`，与 `hierarchy_stuck` 同一份实现），所以步子的落点必须与
        // 普查报的卡点**相同**——不同就是我自己写错了，不用往下读。
        let paths = mesh_paths(&con, &batch, limit);
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            if parse_nodes(&raw).is_empty() || parse_hierarchy(&raw).is_some() {
                continue;
            }
            let Some(sp) = hierarchy_stuck(&raw) else {
                println!("\n{name} · 拿不到卡点（0x110 读不出）");
                continue;
            };
            let (steps, stopped) = tail_walk_steps(&raw, sp.start);
            let n = steps.len();
            println!(
                "\n{name} · 大小 {} · 起点 {} · 普查报的卡点 {} · 轨迹落点 {} · 共 {n} 步{}",
                raw.len(),
                sp.start,
                sp.stopped,
                stopped,
                if stopped == sp.stopped { " ✓一致" } else { " ✗不一致（我写错了）" }
            );
            for (kind, at) in steps.iter().rev().take(20).rev() {
                let w: Vec<String> = (0..4)
                    .map(|k| {
                        raw.get(at + 4 * k..at + 4 * k + 4)
                            .and_then(|b| <[u8; 4]>::try_from(b).ok())
                            .map(u32::from_le_bytes)
                            .map(|v| v.to_string())
                            .unwrap_or_default()
                    })
                    .collect();
                println!(
                    "  {kind:8} @{at}（相对起点 +{}）· 该处 4 个 u32 [{}]",
                    at - sp.start,
                    w.join(", ")
                );
            }
        }
        return;
    }

    if mode == "whytail" {
        // 77 补定下来的下一刀形状：卡点报出来的是**条目起点**（外层只在「这个位置当条目
        // 解析失败」时返回 p），不是断点。于是拿主干**同一个判据函数**在那一点再试一次，
        // 问它「死在哪一步」。只读数——主干一条判据都没改，建树行为不变。
        let paths = mesh_paths(&con, &batch, limit);
        let mut tally: BTreeMap<String, (usize, String)> = BTreeMap::new();
        // 45 那格（条目全对、死在孩子表某槽）单独摊字节：死在哪个偏移、当时读到几个孩子、其后 8 个 u32。
        let mut kid: Vec<String> = Vec::new();
        let mut nam: Vec<String> = Vec::new();
        // 87 补那条矛盾要用「census 读到的字节 vs 解包副本」定版本：这里逐份带上大小与死槽处 4 个 f32。
        let mut det: Vec<String> = Vec::new();
        // 88 补那一刀：name1 那格把「死槽前一字」当表长读，数出权重/id 各有几个不合格。
        let mut audit: BTreeMap<String, usize> = BTreeMap::new();
        let mut fblock: Vec<String> = Vec::new();
        let mut fgap: BTreeMap<String, usize> = BTreeMap::new();
        let mut f156: Vec<String> = Vec::new();
        let (mut files, mut gap, mut nos) = (0usize, 0usize, 0usize);
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            files += 1;
            if parse_nodes(&raw).is_empty() || parse_hierarchy(&raw).is_some() {
                continue;
            }
            gap += 1;
            let (label, ccount, dead) = match hierarchy_stuck(&raw) {
                None => {
                    nos += 1;
                    ("no-stuck-point(0x110 读不出)", 0usize, 0usize)
                }
                Some(sp) if sp.stopped >= raw.len() => ("walked-to-eof(卡的是树闸门)", 0, 0),
                Some(sp) => {
                    if sp.eaten == 0 {
                        ("entry-never-starts", 0, 0)
                    } else {
                        tail_stuck_detail(&raw, sp.stopped)
                    }
                }
            };
            let e = tally.entry(label.to_string()).or_insert((0, name.clone()));
            e.0 += 1;
            if label == "name1-unreadable" && dead >= 4 {
                let (n, vc, bad_id, bad_w, oob) = tail_inf_audit(&raw, dead - 4);
                let k = if oob {
                    "整表越界（长度放不下）".to_string()
                } else if n == 0 {
                    "表长 0（空表本该过判据）".to_string()
                } else if n > vc {
                    format!("表长 {n} > 顶点数 {vc}")
                } else if bad_id == 0 && bad_w == 0 {
                    "四条全合格——那不该判否（待查）".to_string()
                } else if bad_w == 1 && bad_id == 0 {
                    "只 1 个权重不合格 · id 全合".to_string()
                } else if bad_w <= 5 {
                    "权重 2~5 个不合格".to_string()
                } else if bad_w == 0 {
                    "只有 id 不合格（重复或越界）".to_string()
                } else {
                    format!("权重 {bad_w} 个不合格 · id {bad_id}")
                };
                *audit.entry(k).or_insert(0) += 1;
            }
            if label == "name1-unreadable" && dead >= 64 && det.len() < 60 {
                let mut vals = Vec::new();
                for k in 0..16 {
                    let v = raw
                        .get(dead - 64 + 4 * k..dead - 60 + 4 * k)
                        .and_then(|b| <[u8; 4]>::try_from(b).ok())
                        .map_or(0.0f32, f32::from_le_bytes);
                    vals.push(format!("{v:.4}"));
                }
                det.push(format!(
                    "  {name} · 死槽 {dead}(0x{dead:x}) · 该条目声明孩子 {ccount} 个 · 死槽前 64 字节 16 个 f32 [{}]",
                    vals.join(", ")
                ));
            }
            if (label == "child-name-unreadable" && kid.len() < 6)
                || ((label == "name1-unreadable" || label == "flag-not-1") && nam.len() < 12)
            {
                let w = |i: usize| -> u32 {
                    raw.get(dead + 4 * i..dead + 4 * i + 4)
                        .and_then(|b| <[u8; 4]>::try_from(b).ok())
                        .map(u32::from_le_bytes)
                        .unwrap_or(0)
                };
                let words: Vec<String> = (0..8).map(|i| format!("{}", w(i))).collect();
                let mut asc = String::new();
                for k in 0..96 {
                    match raw.get(dead + k) {
                        Some(&b) if (0x20..0x7f).contains(&b) => asc.push(b as char),
                        Some(_) => asc.push('.'),
                        None => break,
                    }
                }
                let row = format!(
                    "  {name} · 声明孩子 {ccount} 个 · 死槽偏移 {dead}(0x{dead:x}) · 其后 8 个 u32 [{}]\n    +0..96 ASCII「{asc}」",
                    words.join(", ")
                );
                if label == "name1-unreadable" {
                    nam.push(row);
                } else {
                    kid.push(row);
                }
            }
            // 93 补那一刀：flag-not-1 这 53 份单独一节——从卡点字往后 1024 字节里
            // 数出所有「ASCII 串 + 紧跟 NUL」的位置，看条目在哪一格重新起、中间夹了多长。
            if label == "flag-not-1" && fblock.len() < 12 {
                let hi = (dead + 1024).min(raw.len());
                let mut hits: Vec<(usize, String)> = Vec::new();
                let mut k = dead;
                while k < hi {
                    let c = raw[k];
                    let isname = c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-' | b'.' | b'(' | b')');
                    if isname {
                        let s = k;
                        while k < hi
                            && (raw[k].is_ascii_alphanumeric()
                                || matches!(raw[k], b'_' | b'-' | b'.' | b'(' | b')'))
                        {
                            k += 1;
                        }
                        if k - s >= 3 && raw.get(k) == Some(&0) {
                            hits.push((s - dead, String::from_utf8_lossy(&raw[s..k]).into_owned()));
                        }
                    } else {
                        k += 1;
                    }
                }
                fblock.push(format!(
                    "  {name} · 卡点字 {dead}(0x{dead:x}) · 往后 1024 字节里的名字段（前 8 个）：{}",
                    hits.iter()
                        .take(8)
                        .map(|(o, t)| format!("+{o} {t}"))
                        .collect::<Vec<_>>()
                        .join(" · ")
                ));
            }
            // 全库分桶（不靠 12 份样本）：往后第一个结构是条目还是挂点、它在卡点字后多少字节。
            if label == "flag-not-1" {
                let hi = (dead + 1024).min(raw.len());
                let mut offs: Vec<(usize, String)> = Vec::new();
                let mut k = dead;
                while k < hi && offs.len() < 4 {
                    let c = raw[k];
                    let isname = c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-' | b'.' | b'(' | b')');
                    if isname {
                        let s = k;
                        while k < hi
                            && (raw[k].is_ascii_alphanumeric()
                                || matches!(raw[k], b'_' | b'-' | b'.' | b'(' | b')'))
                        {
                            k += 1;
                        }
                        if k - s >= 3 && raw.get(k) == Some(&0) {
                            offs.push((s - dead, String::from_utf8_lossy(&raw[s..k]).into_owned()));
                        }
                    } else {
                        k += 1;
                    }
                }
                let key = match (offs.first(), offs.get(1)) {
                    (None, _) => "往后 1024 字节里没有名字段".to_string(),
                    (Some((o0, n0)), Some((o1, n1))) => {
                        let step = o1.saturating_sub(*o0);
                        let kind = if step == 32 && n0 == n1 {
                            "条目（同名隔 32 两遍）"
                        } else if step == 32 {
                            "挂点（名 + 骨名，隔 32）"
                        } else {
                            "别的（首两段不同距或不同名）"
                        };
                        format!("{kind} · 首个在 +{o0}")
                    }
                    (Some((o0, _)), None) => format!("只找到 1 段名字 · 在 +{o0}"),
                };
                *fgap.entry(key.clone()).or_insert(0) += 1;
                // 95 补那一刀：31 份挤在 +160/+164 这两格，把「卡点字往后 156 字节」整段摊成
                // 39 个 u32 打出来（同一份同时给 f32 味道的只看 u32 那串），特征定了再谈加分支。
                if (key.ends_with("+160") || key.ends_with("+164")) && f156.len() < 10 {
                    let mut words = Vec::new();
                    for w in 0..39 {
                        words.push(
                            raw.get(dead + 4 * w..dead + 4 * w + 4)
                                .and_then(|b| <[u8; 4]>::try_from(b).ok())
                                .map(u32::from_le_bytes)
                                .unwrap_or(0)
                                .to_string(),
                        );
                    }
                    let zeros = words.iter().filter(|s| s.as_str() == "0").count();
                    f156.push(format!(
                        "  {name} · {key} · 零字 {zeros}/39 · 39 个 u32 [{}]",
                        words.join(",")
                    ));
                }
            }
        }
        let mut rows: Vec<(String, (usize, String))> = tally.into_iter().collect();
        rows.sort_by(|a, b| b.1.0.cmp(&a.1.0).then_with(|| a.0.cmp(&b.0)));
        println!("\n# 读到 {files} 份 · 有标准记录但建不出树 {gap} 份 · 其中拿不到卡点 {nos} 份");
        println!("# 卡点处「死在哪一步」（份数 · 标签 · 一例）：");
        for (k, (n, ex)) in rows {
            println!("  {n:4} 份 · {k} · 例 {ex}");
        }
        println!("\n# 孩子表那格的死槽字节（前 {} 份 · 偏移是绝对位置）：", kid.len());
        for r in &kid {
            println!("{r}");
        }
        println!(
            "\n# 「读不出第一个名字」与「标志不是 1/-1」两格的**卡点字及其后 96 字节**（前 {} 份）：",
            nam.len()
        );
        for r in &nam {
            println!("{r}");
        }
        println!("\n# name1 那格逐份：死槽前 64 字节的 16 个 f32（摆位型用，前 {} 份）：", det.len());
        for r in &det {
            println!("{r}");
        }
        println!("\n# flag-not-1 那格逐份：卡点字往后 1024 字节里的名字段在哪（前 {} 份）：", fblock.len());
        for r in &fblock {
            println!("{r}");
        }
        println!("\n# flag-not-1 那格**全库**分桶（往后第一个结构是什么 · 它在卡点字后多少字节）：");
        let mut fr: Vec<(String, usize)> = fgap.into_iter().collect();
        fr.sort_by(|a, b| b.1.cmp(&a.1));
        for (k, v) in fr {
            println!("  {v:4} 份 · {k}");
        }
        println!("\n# 挤在 +160/+164 这两格的份，卡点字往后 156 字节 = 39 个 u32（前 {} 份）：", f156.len());
        for r in &f156 {
            println!("{r}");
        }
        println!("\n# name1 那格按「死槽前一字 = 表长」审 id 与权重（份数 · 类别）：");
        let mut ar: Vec<(String, usize)> = audit.into_iter().collect();
        ar.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
        for (k, v) in ar {
            println!("  {v:4} 份 · {k}");
        }
        return;
    }

    if mode == "chaingap" {
        // 57 补冒出来的口子：有些份**标准记录一大把，`parse_hierarchy` 却给不出树**
        // （b5/b7：46 条记录、chainLen=0）。骨架页与骨线都吃这条，之前只报过
        // 「链解得出 2,549/7,996」，没把解不出的分成「本来就没骨架」与「有记录建不出树」两类。
        let paths = mesh_paths(&con, &batch, limit);
        let (mut files, mut std_gt0, mut gap, mut both0) = (0usize, 0usize, 0usize, 0usize);
        // 58 补留下的对账尾巴：「链解得出 2,549」比「有记录且链解得出 2,530」多 19 份，
        // 这 19 份应当是**没有标准记录却解得出链**的——当场数出来点名，别留给下一班猜。
        let (mut no_std_with_chain, mut nswc_ex) = (0usize, Vec::new());
        let mut std_with_chain = 0usize;
        let mut examples: Vec<String> = Vec::new();
        let mut gap_declared = 0usize;
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            files += 1;
            let stdn = parse_nodes(&raw);
            let chain = parse_hierarchy(&raw);
            let clen = chain.map_or(0, |h| h.bones.len());
            if stdn.is_empty() && clen == 0 {
                both0 += 1;
                continue;
            }
            if !stdn.is_empty() {
                std_gt0 += 1;
            }
            if clen > 0 {
                if stdn.is_empty() {
                    no_std_with_chain += 1;
                    if nswc_ex.len() < 6 {
                        nswc_ex.push(format!("{name}(链 {clen} 根)"));
                    }
                } else {
                    std_with_chain += 1;
                }
            }
            if !stdn.is_empty() && clen == 0 {
                gap += 1;
                gap_declared += bone_count(&raw).unwrap_or(0);
                if examples.len() < 12 {
                    examples.push(format!("{name}(标准 {} 条)", stdn.len()));
                }
            }
        }
        println!(
            "\n# 读到 {files} 份 · 标准记录 >0 的 {std_gt0} 份 · **有标准记录但链建不出树的 {gap} 份**\
             （这两者都为零的 {both0} 份）\n\
             # 那 {gap} 份头部声明骨数合计 {gap_declared}\n# 例子：{}",
            examples.join(" · ")
        );
        println!(
            "# 对账：有记录且链解得出 {std_with_chain} 份 · **没记录却链解得出 {no_std_with_chain} 份**（合计链解得出 {}）\n# 后者的例子：{}",
            std_with_chain + no_std_with_chain,
            if nswc_ex.is_empty() { "无".to_string() } else { nswc_ex.join(" · ") }
        );
        return;
    }


    if mode == "localcensus" {
        // 总表 #9（「变体 = 由标准世界值沿父链推出的局部变换」）当时只在 3 份文件 24 根骨上否的，
        // 而今天已经三次栽在「小样本当通则」上。这里铺到全库：同一判据、同一口径，只是人口换成 7,996 份。
        fn mul(a: &[f32; 16], b: &[f32; 16]) -> [f32; 16] {
            let mut o = [0f32; 16];
            for r in 0..4 {
                for c in 0..4 {
                    let mut s = 0f32;
                    for k in 0..4 {
                        s += a[r * 4 + k] * b[k * 4 + c];
                    }
                    o[r * 4 + c] = s;
                }
            }
            o
        }
        let paths = mesh_paths(&con, &batch, limit);
        let (mut files, mut cmpd, mut hit_tight, mut hit_loose, mut hit_1e2) =
            (0usize, 0usize, 0usize, 0usize, 0usize);
        let mut best: Option<f64> = None;
        let mut best_at = String::new();
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            files += 1;
            let var = parse_nodes_variant(&raw);
            if var.is_empty() {
                continue;
            }
            let h = match parse_hierarchy(&raw) {
                Some(h) => h,
                None => continue,
            };
            let stdn = parse_nodes(&raw);
            let bind_of = |nm: &str| stdn.iter().find(|n| n.name == nm).map(|n| n.bind);
            for v in &var {
                let bi = match h.bones.iter().position(|b| b.name == v.name) {
                    Some(i) => i,
                    None => continue,
                };
                let pi = match h.bones[bi].parent {
                    Some(i) => i,
                    None => continue,
                };
                let (Some(wc), Some(wp)) = (bind_of(&v.name), bind_of(&h.bones[pi].name)) else { continue };
                let (Some(w_c), Some(w_p)) = (pose::mat_inverse_affine(&wc), pose::mat_inverse_affine(&wp)) else { continue };
                let l = mul(&w_c, &w_p);
                let d = match diff(&v.bind, &l, &slots16()) {
                    Some(d) => d,
                    None => continue,
                };
                cmpd += 1;
                if d <= 1e-4 {
                    hit_tight += 1;
                } else if d <= 1e-2 {
                    hit_1e2 += 1;
                } else if d <= 1e-1 {
                    hit_loose += 1;
                }
                if best.map_or(true, |b| d < b) {
                    best = Some(d);
                    best_at = format!("{name} · {}", v.name);
                }
            }
        }
        println!(
            "\n# 读到 {files} 份 · 可比的「变体 vs 父链推出的局部」{cmpd} 根\n\
             # 命中：≤1e-4 {hit_tight} · ≤1e-2 {hit_1e2} · ≤1e-1 {hit_loose}\n\
             # 最接近的一根：{}（{best_at}）",
            best.map_or("无可比".to_string(), |d| format!("{d:.6}"))
        );
        return;
    }

    if mode == "mirr" {
        // 最后一个没在全库验过的结构性预言：变体块若真是「这份网格的绑定矩阵」，
        // 它就该满足标准记录那条镜像律——左右同名骨的绑定位移**只差一根轴的符号**
        // （`bind_translations_mirror_left_and_right` 用 5e-3 容差，全库标准记录满足）。
        // 这里只看变体那套，逐对统计满足/不满足。
        let paths = mesh_paths(&con, &batch, limit);
        let (mut files, mut pairs, mut ok, mut bad) = (0usize, 0usize, 0usize, 0usize);
        let mut axis_flip = [0usize; 3];
        // 同一段判据也跑一遍**标准记录**：只有拿到它的「反号轴是根」当基线，
        // 上面变体那串 Z 才有得比（标准那套反的不是 Z 就说明两套约定不同）。
        let (mut s_pairs, mut s_ok, mut s_bad) = (0usize, 0usize, 0usize);
        let mut s_axis = [0usize; 3];
        let near = |x: f32, y: f32| (x - y).abs() < 5e-3;
        let neg = |x: f32, y: f32| (x + y).abs() < 5e-3;
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            files += 1;
            let stdn = parse_nodes(&raw);
            for a in &stdn {
                let Some(rest) = a.name.find("_l_") else { continue };
                let mut mir = a.name.clone();
                mir.replace_range(rest..rest + 3, "_r_");
                let Some(b) = stdn.iter().find(|x| x.name == mir) else { continue };
                let same = (0..3).filter(|k| near(a.bind[12 + k], b.bind[12 + k])).count();
                let flip = (0..3).filter(|k| neg(a.bind[12 + k], b.bind[12 + k])).count();
                s_pairs += 1;
                if same == 2 && flip == 1 {
                    s_ok += 1;
                    for k in 0..3 {
                        if neg(a.bind[12 + k], b.bind[12 + k]) {
                            s_axis[k] += 1;
                        }
                    }
                } else {
                    s_bad += 1;
                }
            }
            let var = parse_nodes_variant(&raw);
            if var.is_empty() {
                continue;
            }
            for a in &var {
                let Some(rest) = a.name.find("_l_") else { continue };
                let mut mir = a.name.clone();
                mir.replace_range(rest..rest + 3, "_r_");
                let Some(b) = var.iter().find(|x| x.name == mir) else { continue };
                let near = |x: f32, y: f32| (x - y).abs() < 5e-3;
                let neg = |x: f32, y: f32| (x + y).abs() < 5e-3;
                let same = (0..3).filter(|k| near(a.bind[12 + k], b.bind[12 + k])).count();
                let flip = (0..3).filter(|k| neg(a.bind[12 + k], b.bind[12 + k])).count();
                pairs += 1;
                if same == 2 && flip == 1 {
                    ok += 1;
                    for k in 0..3 {
                        if neg(a.bind[12 + k], b.bind[12 + k]) {
                            axis_flip[k] += 1;
                        }
                    }
                } else {
                    bad += 1;
                }
            }
        }
        println!(
            "\n# 读到 {files} 份 · 变体里的左右对 {pairs} 组：满足镜像律（两轴同·一轴反号）{ok} · 不满足 {bad}\n\
             # 满足那些组里反号的那根轴：X {} · Y {} · Z {}（标准记录全库是固定一根，若这里散开就说明不是同一套约定）\n\
             # 基线·标准记录：左右对 {s_pairs} 组：满足 {s_ok} · 不满足 {s_bad} · 反号轴 X {} · Y {} · Z {}",
            axis_flip[0], axis_flip[1], axis_flip[2], s_axis[0], s_axis[1], s_axis[2]
        );
        return;
    }

    if mode == "missnames" {
        // 第三十六补留的尾巴：59 份「各差 1 个」——差的到底是哪个名。
        // 只看带变体记录且同目录有解得开的 .ani 的份，把「独有、却在 .ani 骨名表里找不到」的名字点出来。
        let paths = mesh_paths(&con, &batch, limit);
        let mut agg: BTreeMap<String, usize> = BTreeMap::new();
        let mut hit_files = 0usize;
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let Some(raw) = bytes_of(&con, &root, &mut paks, &name) else { continue };
            let std_names: Vec<String> = parse_nodes(&raw).iter().map(|n| n.name.clone()).collect();
            let var = parse_nodes_variant(&raw);
            if var.is_empty() {
                continue;
            }
            let mut bones: Vec<String> = Vec::new();
            for a in anim_names_for(&con, p) {
                let Some(araw) = bytes_of(&con, &root, &mut paks, &a) else { continue };
                let Some(an) = parse_ani(&araw) else { continue };
                bones = an.tracks.iter().map(|t| t.bone.clone()).collect();
                if let Some(rs) = rest_poses(&araw) {
                    for r in rs {
                        if !r.bone.is_empty() && !bones.contains(&r.bone) {
                            bones.push(r.bone);
                        }
                    }
                }
                break;
            }
            if bones.is_empty() {
                continue;
            }
            let missing: Vec<String> = var
                .iter()
                .map(|v| v.name.clone())
                .filter(|n| !std_names.contains(n) && !bones.contains(n))
                .collect();
            if missing.is_empty() {
                continue;
            }
            hit_files += 1;
            for m in &missing {
                *agg.entry(m.clone()).or_default() += 1;
            }
            println!("{name} · {}", missing.join(","));
        }
        println!("\n# 有缺名的份数 {hit_files} · 按名字汇总：");
        let mut rows: Vec<(usize, String)> = agg.into_iter().map(|(k, v)| (v, k)).collect();
        rows.sort_by(|a, b| b.0.cmp(&a.0).then(a.1.cmp(&b.1)));
        for (n, k) in rows.iter().take(25) {
            println!("  {k} · {n} 份");
        }
        return;
    }


    if mode == "pose" {
        // 49 补把两条反证撤了以后，能定性的静态实验只剩这个：
        // 变体与标准**同名的骨**分成两类——整块相同的（只差 ULP）与整块不同的。
        // 若「相同的」恰好是该份动作里**不动的骨**、「不同的」恰好是**会动的骨**，
        // 那变体块就是**同一副骨架在另一个姿态下的绑定**（这条预言可证伪，不用等运行时）。
        let Some(ani) = &ani_name else {
            eprintln!("--mode=pose 要配 --ani=名字.ani");
            std::process::exit(2);
        };
        let araw = match bytes_of(&con, &root, &mut paks, ani) {
            Some(r) => r,
            None => {
                eprintln!("读不出 {ani}");
                std::process::exit(2);
            }
        };
        let an = match parse_ani(&araw) {
            Some(a) => a,
            None => {
                eprintln!("{ani} 解不出动作");
                std::process::exit(2);
            }
        };
        // 会动 = 该骨的位移或旋转在帧间极差 > 1e-4（与判撕那套路数同口径）
        let mut moving: Vec<String> = Vec::new();
        for t in &an.tracks {
            if t.bone.is_empty() {
                continue;
            }
            let span = (0..3).map(|k| {
                let col: Vec<f32> = t.positions.iter().map(|p| p[k]).collect();
                let mn = col.iter().fold(f32::INFINITY, |a, &b| a.min(b));
                let mx = col.iter().fold(f32::NEG_INFINITY, |a, &b| a.max(b));
                mx - mn
            }).collect::<Vec<_>>();
            let rspan = (0..3).map(|k| {
                let col: Vec<f32> = t.rotations.iter().map(|p| p[k]).collect();
                let mn = col.iter().fold(f32::INFINITY, |a, &b| a.min(b));
                let mx = col.iter().fold(f32::NEG_INFINITY, |a, &b| a.max(b));
                mx - mn
            }).collect::<Vec<_>>();
            if span.iter().chain(rspan.iter()).any(|v| *v > 1e-4) {
                moving.push(t.bone.clone());
            }
        }
        println!("\n# {ani} · 轨道 {} 条 · 会动的骨 {} 根", an.tracks.len(), moving.len());
        let (mut ss, mut sd, mut ds, mut dd, mut nomove) = (0usize, 0usize, 0usize, 0usize, 0usize);
        for ld in &loaded {
            for v in &ld.var_nodes {
                let Some(s) = ld.std_nodes.iter().find(|x| x.name == v.name) else { continue };
                let same = diff(&v.bind, &s.bind, &slots16()).map_or(false, |d| d <= 1e-6);
                if !moving.is_empty() && !an.tracks.iter().any(|t| t.bone == v.name) {
                    nomove += 1;
                    continue;
                }
                let mv = moving.contains(&v.name);
                match (same, mv) {
                    (true, false) => ss += 1,
                    (true, true) => sd += 1,
                    (false, false) => ds += 1,
                    (false, true) => dd += 1,
                }
            }
        }
        println!(
            "# 交叉表（变体 vs 同份标准）：相同且不动 {ss} · 相同但会动 {sd} · 不同且不动 {ds} · 不同且会动 {dd} · 无轨道 {nomove}\n\
             # 预言「相同=不动、不同=会动」的话，读 {ss}/{dd} 这两格；{sd} 与 {ds} 是该反例的个数"
        );
        return;
    }

    if mode == "xstd" {
        // 变体块是不是**另一个文件的标准绑定**？第二十七补只比过「同形态的兄弟部件」（0/6），
        // 形态那一维（`_b0`/`_b1`…）没人试过。这里对 `loaded` 里所有有序对做全量对账：
        // A 的变体记录 vs B 的标准记录，同骨名比整块 16 位与纯基向量 12 位两种命中数。
        println!("\n# A 的变体 vs B 的标准（同骨名）：全 16 位命中 / 基向量 12 位命中 / 同名骨数");
        for a in &loaded {
            for b in &loaded {
                if std::ptr::eq(a, b) {
                    continue;
                }
                let mut nm = 0usize;
                let mut full = 0usize;
                let mut basis = 0usize;
                let mut hits: Vec<String> = Vec::new();
                for v in &a.var_nodes {
                    let Some(s) = b.std_nodes.iter().find(|x| x.name == v.name) else { continue };
                    nm += 1;
                    if diff(&v.bind, &s.bind, &slots16()).map_or(false, |d| d <= 1e-4) {
                        full += 1;
                        hits.push(v.name.clone());
                    }
                    if diff(&v.bind, &s.bind, &slots12()).map_or(false, |d| d <= 1e-4) {
                        basis += 1;
                    }
                }
                if nm > 0 {
                    // **同一对文件再比一次「标准 vs 标准」**：48 补查出变体与_own_标准只差 1~4 个 ULP，
                    // 那 30 补「变体跨部件相同 ⇒ 它不是 bind」的推理就取决于一个没验过的前提——
                    // **标准记录本身跨部件是不是也相同**。相同的话那条推理作废。
                    let mut s_nm = 0usize;
                    let mut s_full = 0usize;
                    for x in &a.std_nodes {
                        let Some(y) = b.std_nodes.iter().find(|m| m.name == x.name) else { continue };
                        s_nm += 1;
                        if diff(&x.bind, &y.bind, &slots16()).map_or(false, |d| d <= 1e-4) {
                            s_full += 1;
                        }
                    }
                    println!(
                        "  {} → {}：变体比标准 {full}/{basis}/{nm}；**标准比标准 {s_full}/{s_nm}**{}",
                        a.file.trim_end_matches(".mesh"),
                        b.file.trim_end_matches(".mesh"),
                        if hits.is_empty() {
                            String::new()
                        } else {
                            format!(" 变体命中骨名：{}", hits.join(","))
                        }
                    );
                }
            }
        }
        return;
    }

    if mode == "crosspart" {
        for i in 0..loaded.len() {
            for j in 0..loaded.len() {
                if i >= j {
                    continue;
                }
                let (a, b) = (&loaded[i], &loaded[j]);
                let shared: Vec<&str> = a
                    .var_nodes
                    .iter()
                    .filter_map(|n| {
                        b.var_nodes.iter().any(|m| m.name == n.name).then(|| n.name.as_str())
                    })
                    .collect();
                if shared.is_empty() {
                    continue;
                }
                println!("\n跨部件（变体 vs 变体）：{} · {}", a.file, b.file);
                let (mut eq, mut ne) = (0usize, 0usize);
                for nm in &shared {
                    let va = a.var_nodes.iter().find(|n| &&n.name == nm).unwrap();
                    let vb = b.var_nodes.iter().find(|n| &&n.name == nm).unwrap();
                    match diff(&va.bind, &vb.bind, &slots) {
                        Some(d) => {
                            let same = d <= 1e-6;
                            if same {
                                eq += 1;
                            } else {
                                ne += 1;
                            }
                            println!("  {:<24} 最大差 {:e} {}", nm, d, if same { "对上" } else { "不对上" });
                        }
                        None => println!("  {:<24} 差值无效（非有限）", nm),
                    }
                }
                println!("  同名 {} 个：等 {eq} · 不等 {ne}", shared.len());
            }
        }
        return;
    }

    let mut totals: BTreeMap<&str, usize> = BTreeMap::new();
    let mut grand = 0usize;
    for ld in &loaded {
        println!(
            "\n{} · 声明 {} 根 · 标准 {} 条 · 变体 {} 条",
            ld.file,
            ld.declared.unwrap_or(0),
            ld.std_nodes.len(),
            ld.var_nodes.len()
        );
        let shared: Vec<&str> = ld
            .var_nodes
            .iter()
            .filter_map(|n| ld.std_nodes.iter().any(|m| m.name == n.name).then(|| n.name.as_str()))
            .collect();
        if shared.is_empty() {
            println!("  两套没有同名骨，比不了");
            continue;
        }
        for nm in &shared {
            let v = ld.var_nodes.iter().find(|n| &&n.name == nm).unwrap();
            let s = ld.std_nodes.iter().find(|n| &&n.name == nm).unwrap();
            let inv = pose::mat_inverse_affine(&s.bind);
            let cands: [(&str, Option<[f32; 16]>); 4] = [
                ("本身", Some(s.bind)),
                ("转置", Some(transposed(&s.bind))),
                ("逆", inv),
                ("逆的转置", inv.map(|m: [f32; 16]| transposed(&m))),
            ];
            let mut parts = Vec::new();
            let mut best: Option<(&str, f64)> = None;
            for (label, cand) in cands {
                match cand.and_then(|c| diff(&v.bind, &c, &slots)) {
                    Some(d) => {
                        let hit = d <= 1e-6;
                        if hit {
                            *totals.entry(label).or_default() += 1;
                        }
                        parts.push(format!("{label} {:.3e}", d));
                        if best.map_or(true, |(_, bd)| d < bd) {
                            best = Some((label, d));
                        }
                    }
                    None => parts.push(format!("{label} x")),
                }
            }
            let exact = v.bind == s.bind;
            println!(
                "  {:<24} {} 最近={} 精确等={}",
                nm,
                parts.join(" "),
                best.map_or("无".to_string(), |(l, d)| format!("{l} {d:.6}")),
                exact
            );
        }
        grand += shared.len();
    }
    println!(
        "\n{tag}口径 · {grand} 个同名对比里等于各候选的个数：{:?}（判据：差 ≤1e-6）",
        totals
    );
}
