//! `skel_dump` — 把一只模型的骨架节点与全部动作关键帧导出成一份 JSON。
//!
//! 为什么需要它：`.ani` 的关键帧与 `.mesh` 的骨架节点表都已经能解出来了，
//! 但数据只在这套工具里能看。导出成一份结构化 JSON，才算交给得出去
//! ——Blender 脚本、别的查看器、或者只是想看看某根骨第 12 帧朝哪儿。
//!
//! 导出的同时把**没解出来的东西显式写进文件**（`missing` 字段）：
//! 蒙皮权重在 `influences` 里（按骨组织的影响顶点表）。父骨链在 `parentChain`：
//! `parse_hierarchy` 解出时是骨名到父骨名的列表（根的父为 null，名字用客户端原文），
//! 解不出则为 null，并在 `missing` 里写明这份没读出挂接、不编树。
//! 节点表仍是平铺的，不在每条节点上另挂 `parent`。节点的 `bindPosition` 是
//! 存储矩阵**求逆后**的真实骨位（存储矩阵是世界绑定矩阵的逆，2026-10-06 翻案，
//! 见 `preview::pose::bind_worlds`）；原始矩阵原样在 `bind` 里。
//!
//! 只读纪律：db 只读、pak 只读，只写 `--out` 指定的文件。
//!
//! 用法：
//! ```text
//! skel_dump --root D:/TLGL --name w1351_monster_xiyuqiezei_yifu_001 [--out 目录]
//! skel_dump --root D:/TLGL --ani w1351_monster_xiyuqiezei_walk.ani
//! ```

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use rusqlite::{Connection, OpenFlags};
use serde_json::json;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{bone_count, parse_ani, parse_hierarchy, parse_nodes, SkeletonHierarchy};

/// 在清单里按「文件名结尾」找一条资源，返回 (hash, 所在容器)。
/// 用 `like '%/<name>'` 精确到路径分隔符，避免 `xxx.mesh` 撞进 `xxx.mesh2`。
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

/// 一只模型的动作清单：同一目录下的 `<模型目录>/ani/*.ani`。
/// 客户端的摆放是 `<组目录>/<组名>.mdl`、`<组目录>/ani/<组名>_walk.ani`，
/// 所以按目录取，不按「名字里含模型干名」取——模型干名带部件后缀
/// （`..._yifu_001`），动作名不带，按子串捞会一条也捞不到。
fn anim_names_for(con: &Connection, mesh_path: &str) -> Vec<String> {
    let dir = match mesh_path.rfind('/') {
        Some(i) => &mesh_path[..i],
        None => return Vec::new(),
    };
    let mut out = Vec::new();
    if let Ok(mut stmt) =
        con.prepare("SELECT coalesce(path,'') FROM resources WHERE ext='.ani' AND path LIKE ?1")
    {
        let like = format!("%{dir}/ani/%");
        if let Ok(rows) = stmt.query_map([like], |r| r.get::<_, String>(0)) {
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

/// 清单里一条资源的完整路径（按文件名结尾取第一条）。
fn path_of(con: &Connection, name: &str) -> Option<String> {
    let mut stmt = con
        .prepare("SELECT coalesce(path,'') FROM resources WHERE path LIKE ?1 LIMIT 1")
        .ok()?;
    stmt.query_row([format!("%/{}", name.replace('\'', "''"))], |r| r.get(0))
        .ok()
}

/// 给一个名字（或组干名）找到该导哪份 `.mesh`：先要同名，再要前缀，
/// 前缀命中多份时取字节数最大的那份——主体网格比配件胖，这是本机可验证的启发，
/// 不是客户端写的「主网格」标记（没找到那样的标记，不假装有）。
fn resolve_mesh(con: &Connection, stem: &str) -> Option<String> {
    let base = |p: String| p.rsplit('/').next().unwrap_or("").to_string();
    let exact: Option<String> = con
        .prepare("SELECT coalesce(path,'') FROM resources WHERE ext='.mesh' AND path LIKE ?1 LIMIT 1")
        .ok()
        .and_then(|mut st| st.query_row([format!("%/{stem}.mesh")], |r| r.get(0)).ok());
    if let Some(p) = exact {
        return Some(base(p));
    }
    let part: Option<String> = con
        .prepare("SELECT coalesce(path,'') FROM resources WHERE ext='.mesh' AND path LIKE ?1 ORDER BY stored DESC LIMIT 1")
        .ok()
        .and_then(|mut st| st.query_row([format!("%/{stem}%.mesh")], |r| r.get(0)).ok());
    part.map(base)
}

fn bytes_of(root: &Path, paks: &mut BTreeMap<String, Pak>, hash: u64, pak: &str) -> Option<Vec<u8>> {
    if !paks.contains_key(pak) {
        let opened = Pak::open(&root.join(format!("{pak}.pak"))).ok()?;
        paks.insert(pak.to_string(), opened);
    }
    let p = paks.get(pak)?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(p, &rec).ok().map(|d| d.bytes)
}

/// 一批网格：按路径片段筛，`limit` 兜住别一次跑穿。
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

/// 浮点只留 6 位有效数字。源数据是 f32（本来就只有 7 位有效数字），
/// 而 serde 按 f32 全展开会写成 `0.7071067690849304` 这种 18 个字符；
/// 一只模型 46 骨 × 60 帧 × 8 个浮点，光这个就占掉导出体的一大半。
/// 留 6 位是「不丢工程精度」的下限：四元数分量误差 <1e-6，位移在 1.0 量级。
fn r6(v: f32) -> f32 {
    if v == 0.0 || !v.is_finite() {
        return v;
    }
    let step = 10f32.powf(v.abs().log10().floor() - 5.0);
    (v / step).round() * step
}

fn r4(v: [f32; 4]) -> [f32; 4] {
    v.map(r6)
}

fn r3(v: [f32; 3]) -> [f32; 3] {
    v.map(r6)
}

/// 权重单个浮点留 6 位有效：源数据是 f32，0.99999994 这种写法只让文件变胖。
fn r3x1(v: f32) -> f32 {
    if !v.is_finite() {
        return v;
    }
    (v as f64 * 1e6).round() as f32 / 1e6 as f32
}

fn r16(v: &[f32; 16]) -> Vec<f32> {
    v.iter().map(|x| r6(*x)).collect()
}

/// 父链导出。解出时是骨名 → 父骨名（根的父为 null，名字是客户端原文）；
/// 没解出时值为 null，另一半是写进 `missing` 的说明——不编一棵树。
fn parent_chain_fields(h: Option<&SkeletonHierarchy>) -> (serde_json::Value, Option<&'static str>) {
    let Some(h) = h else {
        return (serde_json::Value::Null, Some("这份没读出挂接，不编一棵树"));
    };
    let rows = h
        .bones
        .iter()
        .map(|b| {
            let parent = b.parent.map(|i| h.bones[i].name.clone());
            json!({
                "name": b.name,
                "parent": parent,
            })
        })
        .collect::<Vec<_>>();
    (json!(rows), None)
}

/// 组一份骨架 + 动作的导出体。
fn build(root: &Path, con: &Connection, mesh: Option<&str>, anis: &[String]) -> serde_json::Value {
    let mut paks: BTreeMap<String, Pak> = BTreeMap::new();
    let mut nodes = json!([]);
    let mut mesh_file = String::new();
    let mut declared = serde_json::Value::Null;
    let mut hierarchy: Option<SkeletonHierarchy> = None;
    if let Some(m) = mesh {
        if let Some((h, pak)) = locate(con, m) {
            if let Some(raw) = bytes_of(root, &mut paks, h, &pak) {
                hierarchy = parse_hierarchy(&raw);
                let got = parse_nodes(&raw);
                if !got.is_empty() {
                    mesh_file = m.to_string();
                    declared = bone_count(&raw).map_or(serde_json::Value::Null, |n| json!(n));
                    nodes = json!(got
                        .iter()
                        .map(|nd| {
                            let mut o = json!({
                                "name": nd.name,
                                // 行主序 4×4 存储矩阵，未加工。它本身是**世界绑定矩阵
                                // 的逆**（2026-10-06 翻案，见 preview::pose::bind_worlds）：
                                // 求逆后第 4 行的平移才是骨位，bindPosition 给的是它，
                                // 不是存储矩阵的末行（末行那套骨架是躺平的）。
                                "bind": r16(&nd.bind),
                            });
                            // 求逆失败（数据坏了）就不放这个键——不拿存储末行凑数。
                            if let Some(b) = tlbb_core::preview::pose::mat_inverse_affine(&nd.bind) {
                                o["bindPosition"] = json!(r3([b[12], b[13], b[14]]));
                            }
                            // 蒙皮权重：按骨组织的影响顶点表，没有就不放这个键（不摆空数组）
                            if let Some(sk) = &nd.skin {
                                o["influences"] = json!({
                                    "vertices": sk.vertices,
                                    "weights": sk.weights.iter().copied().map(r3x1).collect::<Vec<_>>(),
                                });
                            }
                            o
                        })
                        .collect::<Vec<_>>());
                }
            }
        }
    }
    let mut animations = Vec::new();
    for name in anis {
        let Some((h, pak)) = locate(con, name) else { continue };
        let Some(raw) = bytes_of(root, &mut paks, h, &pak) else { continue };
        let Some(a) = parse_ani(&raw) else { continue };
        animations.push(json!({
            "file": name,
            "bones": a.bones,
            "frames": a.frames,
            // 帧率刻度：样本里恒 40.0，含义未证，原样带着不换算成秒
            "tick": a.tick,
            "tracks": a.tracks.iter().map(|t| json!({
                "bone": t.bone,
                "rotations": t.rotations.iter().copied().map(r4).collect::<Vec<_>>(),
                "positions": t.positions.iter().copied().map(r3).collect::<Vec<_>>(),
                "scales": t.scales.iter().copied().map(r6).collect::<Vec<_>>(),
            })).collect::<Vec<_>>(),
        }));
    }
    let (parent_chain, parent_miss) = parent_chain_fields(hierarchy.as_ref());
    let mut missing = json!({
        "tickMeaning": "帧率刻度（样本恒 40.0）到底是每秒 tick 还是别的，未证",
        "skinPerPart": "影响顶点表按份算：同一只怪的衣服那份有 26 根、手套那份一根都没有，所以 nodes 为空或 influences 缺失不代表模型不跟骨走，要换一份网格再看",
        "meshNodesPartial": "mesh 只认出部分骨的节点记录（声明 46 根骨，认出 30 多条）：有些骨的名字后面不跟矩阵。真实骨位（存储矩阵求逆后的平移）只在这些记录里有"
    });
    if let Some(msg) = parent_miss {
        missing["parentChain"] = json!(msg);
    }
    json!({
        "mesh": if mesh_file.is_empty() { serde_json::Value::Null } else { json!(mesh_file) },
        "declaredBones": declared,
        "nodes": nodes,
        "animations": animations,
        "parentChain": parent_chain,
        "missing": missing,
        "provenance": {
            "nodeRecord": "96B = char[32] 名字 + f32[16] 矩阵（D3DX 行向量）。存储矩阵是世界绑定矩阵的逆（B = S⁻¹，2026-10-06 翻案，见 preview::pose::bind_worlds）：bindPosition 是求逆后第 4 行的平移（真实骨位）；存储矩阵的末行 (tx,ty,tz,1) 是逆矩阵的平移，不是骨位，别直接拿去摆骨架",
            "influences": "蒙皮权重在 .mesh：每条 96B 骨记录之后跟 [u32 顶点数 N][N 个顶点号（严格递增）][N 个权重 f32]，是按骨组织的稀疏表，不是每顶点 4 影响的定长表（2026-09-30 实测，闸门 preview::geometry::node_tests::skin_influences_sum_to_one_per_vertex）",
            "restRecord": ".ani 骨架区 60B/骨 = +12 绑定旋转（每条单位长）；+48 那三个浮点用途未证，没往这份导出里放",
            "trackRecord": "每骨每帧 = f32×4 旋转 + f32×3 位移 + f32 缩放",
            "boneCountField": ".mesh 头部 0x110 处的 u32 = 骨骼根数，与该模型 .ani 的轨道数一致",
            "animationsMatched": "动作按「同目录的 ani/ 子目录」整批配给网格：一只怪的部件网格共用一组动作是对的，但一个目录里放多只互不相关的模型时，每份网格都会拿到该目录的全部动作——批量导出时若 nodes 为 0（静态网格没有骨架节点），这批动作多半不属于它",
            "parentChain": "父链来自尾部各条目孩子名单的并：解出时 parentChain 是骨名到父骨名的列表（根的父为 null，名字用客户端原文），没读出挂接时为 null",
            "generator": "skel_dump (tlbb-core preview::{parse_nodes, parse_ani, bone_count, parse_hierarchy})"
        }
    })
}

fn main() {
    let mut root = PathBuf::from("D:/TLGL");
    let mut db: Option<PathBuf> = None;
    let mut out = PathBuf::from(".scratch/skel_dump");
    let mut mesh: Option<String> = None;
    let mut one_ani: Option<String> = None;
    let mut batch: Option<String> = None;
    let mut limit: usize = 20;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--root" => root = PathBuf::from(args.next().unwrap_or_default()),
            "--db" => db = Some(PathBuf::from(args.next().unwrap_or_default())),
            "--out" => out = PathBuf::from(args.next().unwrap_or_default()),
            "--name" => mesh = Some(args.next().unwrap_or_default()),
            "--ani" => one_ani = Some(args.next().unwrap_or_default()),
            "--batch" => batch = Some(args.next().unwrap_or_default()),
            "--limit" => limit = args.next().unwrap_or_default().parse().unwrap_or(20),
            other => eprintln!("未知参数 {other}"),
        }
    }
    let db = db.unwrap_or_else(|| root.join(".scratch/resources.db"));
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

    // 批量：一条命令出一批模型的骨架 JSON。
    // 为什么要批量：一只一只点名太慢，而下游（Blender 脚本、别的查看器）要的是
    // 一批。没有动作的静态网格跳过——那份文件里只有几何，导出来是空壳。
    if let Some(prefix) = &batch {
        let paths = mesh_paths(&con, prefix, limit);
        std::fs::create_dir_all(&out).ok();
        let (mut done, mut nodes, mut anims) = (0usize, 0usize, 0usize);
        for p in &paths {
            let name = p.rsplit('/').next().unwrap_or("").to_string();
            let list = anim_names_for(&con, p);
            if list.is_empty() {
                continue;
            }
            let v = build(&root, &con, Some(&name), &list);
            let n = v["nodes"].as_array().map_or(0, |a| a.len());
            let k = v["animations"].as_array().map_or(0, |a| a.len());
            let file = out.join(format!("{}.skel.json", name.trim_end_matches(".mesh").replace('/', "_")));
            match std::fs::write(&file, serde_json::to_string(&v).unwrap_or_default()) {
                Ok(_) => {
                    done += 1;
                    nodes += n;
                    anims += k;
                    println!("  {name} · 节点 {n} · 动作 {k}");
                }
                Err(e) => eprintln!("  {name} 写不出去：{e}"),
            }
        }
        println!(
            "批量：扫了 {} 份网格，出了 {done} 份骨架 JSON（节点 {nodes} 条 · 动作 {anims} 条）→ {}",
            paths.len(),
            out.display()
        );
        return;
    }

    // --name 给的是 .mesh 文件名，或「组干名」——组干名本身没有同名 .mesh，
    // 部件才有（`<组名>_yifu_001.mesh`），所以先找同名，再按前缀取最大的一份。
    let (mesh_file, anis) = match (&one_ani, &mesh) {
        (Some(a), None) => (None, vec![a.clone()]),
        (Some(_), Some(_)) => {
            eprintln!("--name 与 --ani 只能给一个");
            std::process::exit(2);
        }
        (None, Some(n)) => {
            let mf = resolve_mesh(&con, n.trim_end_matches(".mesh"));
            let anis = mf
                .as_deref()
                .and_then(|m| path_of(&con, m))
                .map(|p| anim_names_for(&con, &p))
                .unwrap_or_default();
            (mf, anis)
        }
        (None, None) => {
            eprintln!("用法：skel_dump [--root DIR] [--name 模型名 | --ani x.ani | --batch 路径片段 [--limit N]] [--out DIR]");
            std::process::exit(2);
        }
    };

    let v = build(&root, &con, mesh_file.as_deref(), &anis);
    std::fs::create_dir_all(&out).ok();
    let tag = one_ani.clone().or(mesh.clone()).unwrap_or_else(|| "bundle".into());
    let file = out.join(format!("{}.skel.json", tag.trim_end_matches(".mesh").replace('/', "_")));
    // 单份导出留 pretty（人要打开看的就是这一份，体积不敏感）；批量走紧凑格式
    let body = if batch.is_some() {
        serde_json::to_string(&v).unwrap_or_default()
    } else {
        serde_json::to_string_pretty(&v).unwrap_or_default()
    };
    if let Err(e) = std::fs::write(&file, &body) {
        eprintln!("写不出 {}：{e}", file.display());
        std::process::exit(2);
    }
    println!(
        "{} · 节点 {} 个 · 动作 {} 条 → {}",
        tag,
        v["nodes"].as_array().map_or(0, |a| a.len()),
        v["animations"].as_array().map_or(0, |a| a.len()),
        file.display()
    );
    if let Some(first) = v["animations"].as_array().and_then(|a| a.first()) {
        println!(
            "  第一条：{} · {} 骨 · {} 帧",
            first["file"].as_str().unwrap_or("?"),
            first["bones"].as_u64().unwrap_or(0),
            first["frames"].as_u64().unwrap_or(0)
        );
    }
    println!("  蒙皮权重在 influences；父骨链在 parentChain；其余未解项在 missing");
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 真数据：走一遍 main 的找文件路径（组干名 → 部件 mesh → 同组 ani），
    /// 导出来的数要和自己解出来的一致，没解出来的东西必须写在文件里。
    #[test]
    fn dump_carries_nodes_tracks_and_says_what_is_missing() {
        let root = std::env::var("TLBB_ROOT")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
        let db = root.join(".scratch/resources.db");
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端或资源清单");
            return;
        }
        let con = Connection::open_with_flags(
            &db,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .expect("清单");
        // 给的是组干名，不带部件后缀——这正是上一版捞不到动作的那个入口
        let mesh = resolve_mesh(&con, "w1351_monster_xiyuqiezei").expect("该找到部件 mesh");
        let path = path_of(&con, &mesh).expect("mesh 的完整路径");
        let anis = anim_names_for(&con, &path);
        assert!(!anis.is_empty(), "同组 ani/ 目录下该有一批动作，实际 0 条");
        let v = build(&root, &con, Some(&mesh), &anis[..anis.len().min(3)]);
        let declared = v["declaredBones"].as_u64().unwrap() as usize;
        let nodes = v["nodes"].as_array().expect("节点数组");
        assert!(nodes.len() >= 30, "只读出 {} 个节点（头部声明 {declared} 根骨）", nodes.len());
        assert_eq!(nodes[0]["name"].as_str(), Some("origin"));
        assert_eq!(nodes[0]["bind"].as_array().map(|a| a.len()), Some(16));
        assert_eq!(nodes[0]["bindPosition"].as_array().map(|a| a.len()), Some(3));
        // 蒙皮权重：按骨的影响顶点表必须进导出文件，且不许再出现在「未解」里
        let with_inf: Vec<_> = nodes
            .iter()
            .filter(|nd| nd["influences"]["vertices"].as_array().map_or(false, |a| !a.is_empty()))
            .collect();
        assert!(
            with_inf.len() >= 20,
            "这份网格实测 26 根骨带影响顶点表，导出里只有 {}",
            with_inf.len()
        );
        for nd in &with_inf {
            let v = nd["influences"]["vertices"].as_array().unwrap();
            let w = nd["influences"]["weights"].as_array().unwrap();
            assert_eq!(v.len(), w.len(), "顶点号与权重个数该相等");
            assert!(
                v.windows(2).all(|p| p[0].as_u64().unwrap() < p[1].as_u64().unwrap()),
                "顶点号该严格递增"
            );
        }
        assert!(
            v["missing"].get("skinWeights").is_none(),
            "权重已解，不许还挂在 missing 里"
        );
        assert!(v["provenance"]["influences"].is_string(), "出处要写清");
        // 左右镜像对在翻案后的口径（存储值求逆）下同样成立：求逆保持镜像。
        // 左右同名骨只差一根轴的符号，读歪一个字段就断。
        let mut pairs = 0;
        for nd in nodes.iter() {
            let nm = nd["name"].as_str().unwrap();
            let Some(rest) = nm.strip_prefix("bip01_l_") else { continue };
            let Some(other) = nodes.iter().find(|x| x["name"].as_str() == Some(&format!("bip01_r_{rest}"))) else { continue };
            let mut same = 0;
            let mut flipped = 0;
            for k in 0..3 {
                let a = nd["bindPosition"][k].as_f64().unwrap();
                let b = other["bindPosition"][k].as_f64().unwrap();
                // 建模时左右不完全对等，5e-3 够（骨长量级 1.0）
                if (a - b).abs() < 5e-3 {
                    same += 1;
                } else if (a + b).abs() < 5e-3 {
                    flipped += 1;
                }
            }
            assert_eq!((same, flipped), (2, 1), "{nm} 与它的右侧不像镜像：{same} 个相同 {flipped} 个相反");
            pairs += 1;
        }
        assert!(pairs >= 4, "镜像对太少（{pairs}），这份导出的绑定位移没被验到");
        // 口径钉住（2026-10-06 翻案）：bindPosition 是存储矩阵求逆后的骨位，
        // 不是存储末行——两种读法必须区分得开，脚趾要站在解剖高度上。
        let pelvis = nodes
            .iter()
            .find(|nd| nd["name"].as_str() == Some("bip01_pelvis"))
            .expect("pelvis 在节点表里");
        let stored: Vec<f64> = pelvis["bind"].as_array().unwrap()[12..15]
            .iter()
            .map(|v| v.as_f64().unwrap())
            .collect();
        let pos: Vec<f64> = pelvis["bindPosition"]
            .as_array()
            .expect("pelvis 的矩阵求得出逆")
            .iter()
            .map(|v| v.as_f64().unwrap())
            .collect();
        assert!(
            stored.iter().zip(&pos).any(|(a, b)| (a - b).abs() > 1e-3),
            "pelvis 的存储末行与求逆骨位居然一样，这条钉子没有分辨力：{stored:?} vs {pos:?}"
        );
        let toe = nodes
            .iter()
            .find(|nd| nd["name"].as_str() == Some("bip01_l_toe0"))
            .expect("toe0 在节点表里");
        let ty = toe["bindPosition"][1].as_f64().expect("toe0 的 y");
        assert!((ty - 0.140).abs() < 0.02, "脚趾该站在解剖高度 y≈0.140（求逆后骨位），实际 {ty}");
        let anims = v["animations"].as_array().expect("动作数组");
        assert!(!anims.is_empty(), "一条动作都没导出来");
        let a0 = &anims[0];
        let bones = a0["bones"].as_u64().unwrap() as usize;
        let frames = a0["frames"].as_u64().unwrap() as usize;
        let tracks = a0["tracks"].as_array().unwrap();
        assert_eq!(bones, declared, "动作轨道数应等于 mesh 头部声明的骨骼数（两份容器对账）");
        assert_eq!(tracks.len(), bones, "轨道数必须等于骨骼数");
        for t in tracks.iter() {
            assert_eq!(t["rotations"].as_array().unwrap().len(), frames);
            assert_eq!(t["positions"].as_array().unwrap().len(), frames);
        }
        // 父链已解：骨名到父骨名，根的父为 null；不许再写成「未解」，也不许改名
        let chain = v["parentChain"].as_array().expect("主样本应解出父链");
        assert_eq!(chain.len(), declared, "父链应覆盖头部声明的每一根骨");
        let mut names = std::collections::BTreeSet::new();
        let mut roots = 0usize;
        for row in chain {
            let name = row["name"].as_str().expect("骨名");
            assert!(names.insert(name.to_string()), "骨名重复：{name}");
            if row["parent"].is_null() {
                roots += 1;
                assert_eq!(name, "000", "唯一根应是客户端原文 000");
            } else {
                assert!(row["parent"].is_string(), "{name} 的父应是骨名");
            }
        }
        assert_eq!(roots, 1, "应是单根");
        for row in chain {
            if let Some(p) = row["parent"].as_str() {
                assert!(names.contains(p), "{} 的父 {p} 不在链上", row["name"].as_str().unwrap());
            }
        }
        let parent_of = |n: &str| {
            chain
                .iter()
                .find(|r| r["name"].as_str() == Some(n))
                .unwrap_or_else(|| panic!("链上该有 {n}"))["parent"]
                .as_str()
        };
        assert_eq!(parent_of("bip01"), Some("000"));
        assert_eq!(parent_of("bip01_pelvis"), Some("bip01"));
        assert_eq!(parent_of("bip01_l_thigh"), Some("bip01_spine"));
        assert!(
            v["missing"].get("parentChain").is_none(),
            "父链已解，不许还挂在 missing 里"
        );
        let prov = v["provenance"]["parentChain"].as_str().expect("出处要写清父链");
        assert!(prov.contains("孩子名单"), "出处应说明父链来自孩子名单的并：{prov}");
        let dumped = v.to_string();
        assert!(!dumped.contains("父骨链未解"), "过时的「未解」说明不该再出现");
        assert!(!dumped.contains("父索引"), "不该再写父索引字段不存在");
        // 没解出来的东西必须写在文件里，不能让人自己发现
        assert!(v["missing"]["tickMeaning"].is_string());
        assert!(v["provenance"]["boneCountField"].is_string());
        eprintln!(
            "导出：{mesh} · 声明 {declared} 骨 · mesh 节点 {} 条（左右镜像对 {pairs} 对）· 动作 {} 条（第一条 {bones} 骨 {frames} 帧）",
            nodes.len(),
            anims.len()
        );
    }

    /// 批量入口的取文件逻辑：按路径片段筛网格、认得出 .mesh、条数受 limit 管。
    #[test]
    fn batch_selects_meshes_under_a_prefix() {
        let root = std::env::var("TLBB_ROOT")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
        let db = root.join(".scratch/resources.db");
        if !db.is_file() {
            eprintln!("跳过：本机没有资源清单");
            return;
        }
        let con = Connection::open_with_flags(
            &db,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .expect("清单");
        let all = mesh_paths(&con, "npc/quest/w1351_monster_xiyuqiezei", 50);
        assert!(!all.is_empty(), "这只怪名下该有网格");
        assert!(all.iter().all(|p| p.ends_with(".mesh")), "只该挑出 .mesh");
        let few = mesh_paths(&con, "npc/quest/w1351_monster_xiyuqiezei", 1);
        assert_eq!(few.len(), 1, "limit 必须真起作用");
        // 挑出来的网格得能配上动作——否则批量等于白跑
        let with_anim = all.iter().filter(|p| !anim_names_for(&con, p).is_empty()).count();
        assert!(with_anim >= 1, "批量选出的网格里一个带动作的都没有，这条入口没意义");
        eprintln!("批量：筛出 {} 份网格，其中 {with_anim} 份带动作", all.len());
    }

    /// 只给一个 `.ani` 也要能出活：没有 mesh 就没有节点记录，但动作照样导。
    #[test]
    fn single_animation_dumps_without_a_mesh() {
        let root = std::env::var("TLBB_ROOT")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
        let db = root.join(".scratch/resources.db");
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端或资源清单");
            return;
        }
        let con = Connection::open_with_flags(
            &db,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .expect("清单");
        let v = build(
            &root,
            &con,
            None,
            &["w1351_monster_xiyuqiezei_run.ani".to_string()],
        );
        assert!(v["nodes"].as_array().unwrap().is_empty(), "没给 mesh 就不该有节点");
        assert!(v["mesh"].is_null());
        assert!(v["parentChain"].is_null(), "没给网格就不该编父骨链");
        let msg = v["missing"]["parentChain"].as_str().expect("没读出挂接要写明");
        assert!(msg.contains("没读出挂接"), "{msg}");
        assert!(msg.contains("不编"), "{msg}");
        assert!(!msg.contains("父索引"), "{msg}");
        let anims = v["animations"].as_array().unwrap();
        assert_eq!(anims.len(), 1, "应当正好导出一条动作");
        assert_eq!(anims[0]["file"].as_str(), Some("w1351_monster_xiyuqiezei_run.ani"));
    }

    /// 父链形状：解出是骨名对父骨名，根为 null；没解出是 null 加一句说明，不编树。
    #[test]
    fn parent_chain_is_name_pairs_or_an_explicit_miss() {
        use tlbb_core::preview::BoneNode;

        let h = SkeletonHierarchy {
            bones: vec![
                BoneNode {
                    name: "000".into(),
                    parent: None,
                    bind: None,
                    children: vec![1],
                },
                BoneNode {
                    name: "bip01_spine".into(),
                    parent: Some(0),
                    bind: None,
                    children: vec![],
                },
            ],
            sockets: vec![],
        };
        let (chain, miss) = parent_chain_fields(Some(&h));
        assert!(miss.is_none());
        let rows = chain.as_array().expect("结构化列表");
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0]["name"].as_str(), Some("000"));
        assert!(rows[0]["parent"].is_null());
        assert_eq!(rows[1]["name"].as_str(), Some("bip01_spine"));
        assert_eq!(rows[1]["parent"].as_str(), Some("000"));

        let (chain, miss) = parent_chain_fields(None);
        assert!(chain.is_null(), "没读出挂接时不编树");
        let msg = miss.expect("要写明没读出");
        assert!(msg.contains("没读出挂接"), "{msg}");
        assert!(!msg.contains("父索引"), "{msg}");
        assert!(!msg.contains("父骨链未解"), "{msg}");
    }
}
