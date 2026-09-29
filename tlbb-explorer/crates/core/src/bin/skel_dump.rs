//! `skel_dump` — 把一只模型的骨架节点与全部动作关键帧导出成一份 JSON。
//!
//! 为什么需要它：`.ani` 的关键帧与 `.mesh` 的骨架节点表都已经能解出来了，
//! 但数据只在这套工具里能看。导出成一份结构化 JSON，才算交给得出去
//! ——Blender 脚本、别的查看器、或者只是想看看某根骨第 12 帧朝哪儿。
//!
//! 导出的同时把**没解出来的东西显式写进文件**（`missing` 字段）：
//! 父骨链与蒙皮权重未知，所以这份 JSON 里每个节点都是平铺的，
//! 没有 `parent`，也没有 `weights`。拿到它的人不必猜少了不少什么。
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
use tlbb_core::preview::{bone_count, parse_ani, parse_nodes};

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

fn r16(v: &[f32; 16]) -> Vec<f32> {
    v.iter().map(|x| r6(*x)).collect()
}

/// 组一份骨架 + 动作的导出体。
fn build(root: &Path, con: &Connection, mesh: Option<&str>, anis: &[String]) -> serde_json::Value {
    let mut paks: BTreeMap<String, Pak> = BTreeMap::new();
    let mut nodes = json!([]);
    let mut mesh_file = String::new();
    let mut declared = serde_json::Value::Null;
    if let Some(m) = mesh {
        if let Some((h, pak)) = locate(con, m) {
            if let Some(raw) = bytes_of(root, &mut paks, h, &pak) {
                let got = parse_nodes(&raw);
                if !got.is_empty() {
                    mesh_file = m.to_string();
                    declared = bone_count(&raw).map_or(serde_json::Value::Null, |n| json!(n));
                    nodes = json!(got
                        .iter()
                        .map(|nd| json!({
                            "name": nd.name,
                            // 行主序 4×4；前三行基向量，第四行 (tx,ty,tz,1) 是绑定位移
                            "bind": r16(&nd.bind),
                            "bindPosition": r3([nd.bind[12], nd.bind[13], nd.bind[14]]),
                        }))
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
    json!({
        "mesh": if mesh_file.is_empty() { serde_json::Value::Null } else { json!(mesh_file) },
        "declaredBones": declared,
        "nodes": nodes,
        "animations": animations,
        "missing": {
            "parentChain": "父骨链未解：96 字节节点记录 = 名字 char[32] + 矩阵 f32[16]，排不出父索引的槽位；名字之后还跟着几段名单（子骨名单？用途未证）",
            "skinWeights": "蒙皮权重未解：.mesh 中段是法线+UV，节点表之后也排不出「4 索引 + 4 权重和为 1」",
            "tickMeaning": "帧率刻度（样本恒 40.0）到底是每秒 tick 还是别的，未证",
            "meshNodesPartial": "mesh 只认出部分骨的节点记录（声明 46 根骨，认出 30 多条）：有些骨的名字后面不跟矩阵。绑定位移只在这些记录里有"
        },
        "provenance": {
            "nodeRecord": "96B = char[32] 名字 + f32[16] 绑定矩阵（D3DX 行向量：末行 tx,ty,tz,1）",
            "restRecord": ".ani 骨架区 60B/骨 = +12 绑定旋转（每条单位长）；+48 那三个浮点用途未证，没往这份导出里放",
            "trackRecord": "每骨每帧 = f32×4 旋转 + f32×3 位移 + f32 缩放",
            "boneCountField": ".mesh 头部 0x110 处的 u32 = 骨骼根数，与该模型 .ani 的轨道数一致",
            "generator": "skel_dump (tlbb-core preview::{parse_nodes, parse_ani, bone_count})"
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
    println!("  未解项已写进 missing 字段（父骨链 / 蒙皮权重 / 帧率刻度的含义）");
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
        // 绑定位移是真的在骨架空间里：左右同名骨必须只差一根轴的符号
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
        // 没解出来的东西必须写在文件里，不能让人自己发现
        assert!(v["missing"]["parentChain"].is_string());
        assert!(v["missing"]["skinWeights"].is_string());
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
        let anims = v["animations"].as_array().unwrap();
        assert_eq!(anims.len(), 1, "应当正好导出一条动作");
        assert_eq!(anims[0]["file"].as_str(), Some("w1351_monster_xiyuqiezei_run.ani"));
    }
}
