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
use tlbb_core::preview::{bone_count, parse_ani, parse_hierarchy, parse_nodes, parse_nodes_variant, rest_poses, pose};

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
    if names.is_empty() && mode != "gain" && mode != "missnames" && mode != "skin" {
        eprintln!("用法：variant_probe [--root DIR] [--mode same|12slot|trans|axis|crosspart|rest|gain|missnames|skin] 干名[,...]");
        eprintln!("      批量：variant_probe --mode=gain|missnames|skin --batch=路径片段 [--limit=N]");
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
    if loaded.is_empty() && mode != "gain" && mode != "missnames" && mode != "skin" {
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
                        parts.push(format!("{label} {:.4}", d));
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
