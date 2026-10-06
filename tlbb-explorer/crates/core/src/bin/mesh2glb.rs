//! 批量把解包目录里的 `.mesh` 导成 `.glb` + 一份给网页用的 `manifest.json`。
//!
//! 用法：
//! ```text
//! mesh2glb --tree=D:\TLGL\.scratch\out\tree --db=D:\TLGL\.scratch\resources.db \
//!          --out=D:\TLGL\web-viewer\model [--limit=N] [--rigged]
//! ```
//!
//! `--rigged`（2026-10-05）：对每份网格先试 `parse_hierarchy` 解骨架，解得出来
//! 就把同目录 `ani/*.ani` 一并配进 `to_glb_rigged`（骨架 node 树 + skin + 动画）。
//! 解不出骨架的网格照旧走静态导出；rigged 导出本身失败则记入 `failures`
//! 并回退静态（原用法不受影响）。rigged 产物在 manifest 里带 `"rigged": true`
//! 与 `animations` 名单。
//!
//! 纪律：
//! - 只读库（`mode=ro`）、只读解包目录，产物只往 `--out` 写；
//! - 内容相同的网格共用一个 `.glb`（全库有一万六千个文件是别人的字节复制）；
//! - 解不出来的一律进 `failures`，带上解析器的原话，**不降级、不凑数**；
//! - manifest 的键是英文（数据层），中文只出现在值里（分类走 `catalog::labels`）；
//! - 清单里不放客户端编号：`id` 是内容指纹（crc32 + 长度），与 hash 无关。

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use rusqlite::Connection;
use serde_json::{json, Value};
use tlbb_core::catalog::labels::kind_zh;
use tlbb_core::export::gltf::{to_glb, to_glb_rigged, RigExport};
use tlbb_core::preview::parse_ani;
use tlbb_core::preview::{parse_hierarchy, parse_mesh, parse_nodes, Anim, MeshLayout};

fn arg(argv: &[String], name: &str) -> Option<String> {
    let want = format!("--{name}=");
    argv.iter()
        .skip(1)
        .find_map(|a| a.strip_prefix(&want).map(|s| s.trim_matches('"').to_string()))
}

fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
    if let Ok(rd) = std::fs::read_dir(dir) {
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                walk(&p, out);
            } else if p
                .extension()
                .map(|x| x.eq_ignore_ascii_case("mesh"))
                .unwrap_or(false)
            {
                out.push(p);
            }
        }
    }
}

fn content_id(raw: &[u8]) -> String {
    format!("{:08x}{:08x}", crc32fast::hash(raw), raw.len() as u32)
}

fn has_flag(argv: &[String], name: &str) -> bool {
    argv.iter().skip(1).any(|a| a == name)
}

/// rigged 导出：骨架解得出才走这条路（None）；解得出但导出失败回 Err（调用方
/// 记入 failures 后回退静态）。成功回 (glb 字节, 动作名单, 被跳过的 .ani 及原因)。
fn rigged_glb(
    tree: &Path,
    rel: &str,
    stem: &str,
    raw: &[u8],
    l: &MeshLayout,
) -> Option<Result<(Vec<u8>, Vec<String>, Vec<String>), String>> {
    let hierarchy = parse_hierarchy(raw)?;
    let influences = parse_nodes(raw);
    // 动作在网格同目录的 ani/ 子目录里（客户端摆放：<组名>_<动作>.ani）。
    // 展示名剥掉与网格干名的公共前缀（`w1351_monster_xiyuqiezei_idle01` 对
    // `…_yifu_001` → `idle01`）——前缀来自两份文件名本身，是事实不是猜的；
    // 剥不出（公共前缀空 / 整条被吃掉）就保留原干名。
    let mut anims: Vec<(String, Anim)> = Vec::new();
    let mut skipped: Vec<String> = Vec::new();
    let rel_path = Path::new(rel);
    let common = |other: &str| -> String {
        let a = stem.as_bytes();
        let b = other.as_bytes();
        let n = a.iter().zip(b.iter()).take_while(|(x, y)| x == y).count();
        let cut = a[..n].iter().rposition(|&c| c == b'_').map_or(0, |i| i + 1);
        String::from_utf8_lossy(&a[..cut]).into_owned()
    };
    if let Some(dir) = rel_path.parent() {
        let ani_dir = tree.join(dir).join("ani");
        if let Ok(rd) = std::fs::read_dir(&ani_dir) {
            let mut paths: Vec<PathBuf> = rd
                .flatten()
                .map(|e| e.path())
                .filter(|p| p.extension().map(|x| x.eq_ignore_ascii_case("ani")).unwrap_or(false))
                .collect();
            paths.sort();
            for p in paths {
                let stem_ani =
                    p.file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
                let raw_ani = match std::fs::read(&p) {
                    Ok(r) => r,
                    Err(e) => {
                        skipped.push(format!("{stem_ani}: 读失败 {e}"));
                        continue;
                    }
                };
                match parse_ani(&raw_ani) {
                    Some(a) => {
                        let pre = common(&stem_ani);
                        let name = match stem_ani.strip_prefix(&pre) {
                            Some(r) if !r.is_empty() && !pre.is_empty() => r.to_string(),
                            _ => stem_ani.clone(),
                        };
                        anims.push((name, a));
                    }
                    None => skipped.push(format!("{stem_ani}: parse_ani 不认")),
                }
            }
        }
    }
    let rig = RigExport { hierarchy: &hierarchy, influences: &influences };
    let refs: Vec<(&str, &Anim)> = anims.iter().map(|(n, a)| (n.as_str(), a)).collect();
    match to_glb_rigged(stem, l, &[], Some(&rig), &refs) {
        Ok(bytes) => {
            let names = anims.into_iter().map(|(n, _)| n).collect();
            Some(Ok((bytes, names, skipped)))
        }
        Err(e) => Some(Err(e)),
    }
}

/// 按**客户端目录**给的分桶（是路径事实，不是对内容的猜测）。
/// 库里归好类的组另有 `groupKind` 字段，两者分开摆，不混成一件事。
fn dir_category(dir: &str) -> &'static str {
    if dir.starts_with("mobile_maps_source") {
        "地图资源"
    } else if dir.starts_with("data/source/npc") {
        "NPC 与怪物"
    } else if dir.starts_with("data/source/player") {
        "玩家角色"
    } else if dir.starts_with("data/effect") {
        "特效模型"
    } else if dir.contains("/ui/") || dir.starts_with("data/ui") {
        "界面资源"
    } else {
        "其它目录"
    }
}

fn stem(rel: &str) -> String {
    Path::new(rel)
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_default()
}

fn parent(rel: &str) -> String {
    Path::new(rel)
        .parent()
        .map(|p| p.to_string_lossy().replace('\\', "/"))
        .unwrap_or_default()
}

struct Maps {
    /// 客户端路径（小写）→ 所属资产组
    gid_by_path: HashMap<String, i64>,
    /// 组 → (类型键, 引用总数, 其中定位到实体的)
    group: HashMap<i64, (String, usize, usize)>,
    /// 组 → 中文标签（由路径/角色/引用规则推出，不是猜的）
    tags: HashMap<i64, Vec<String>>,
}

fn load_db(path: &str) -> Result<Maps, String> {
    let conn = Connection::open_with_flags(
        format!("file:{}?mode=ro", path.replace('\\', "/")),
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    )
    .map_err(|e| format!("打不开只读库 {path}：{e}"))?;
    let mut m = Maps {
        gid_by_path: HashMap::new(),
        group: HashMap::new(),
        tags: HashMap::new(),
    };

    let mut st = conn
        .prepare(
            "SELECT lower(r.path), m.gid FROM amembers m \
             JOIN resources r ON r.hash = m.hash WHERE r.path IS NOT NULL AND r.path <> ''",
        )
        .map_err(|e| e.to_string())?;
    for r in st
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)))
        .map_err(|e| e.to_string())?
        .flatten()
    {
        m.gid_by_path.insert(r.0, r.1);
    }

    // 引用健康度按整组统计：一个网格属于哪个组，就共享那组的账。
    let mut st = conn
        .prepare(
            "SELECT m.gid, a.kind, count(*), \
             sum(CASE WHEN r.to_hash IS NULL THEN 0 ELSE 1 END) \
             FROM refs r JOIN amembers m ON m.hash = r.from_hash \
             JOIN agroups a ON a.id = m.gid GROUP BY m.gid",
        )
        .map_err(|e| e.to_string())?;
    for r in st
        .query_map([], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                (
                    r.get::<_, String>(1)?,
                    r.get::<_, i64>(2)? as usize,
                    r.get::<_, Option<i64>>(3)?.unwrap_or(0) as usize,
                ),
            ))
        })
        .map_err(|e| e.to_string())?
        .flatten()
    {
        m.group.insert(r.0, r.1);
    }

    let mut st = conn
        .prepare("SELECT gid, tag FROM asset_tags ORDER BY gid")
        .map_err(|e| e.to_string())?;
    for r in st
        .query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)))
        .map_err(|e| e.to_string())?
        .flatten()
    {
        m.tags.entry(r.0).or_default().push(r.1);
    }
    Ok(m)
}

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let tree = arg(&argv, "tree").unwrap_or_else(|| r"D:\TLGL\.scratch\out\tree".to_string());
    let db = arg(&argv, "db").unwrap_or_else(|| r"D:\TLGL\.scratch\resources.db".to_string());
    let out = arg(&argv, "out").unwrap_or_else(|| r"D:\TLGL\web-viewer\model".to_string());
    let limit: usize = arg(&argv, "limit")
        .and_then(|s| s.parse().ok())
        .unwrap_or(usize::MAX);
    let rigged = has_flag(&argv, "--rigged");

    let maps = match load_db(&db) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(2);
        }
    };

    let mut files = Vec::new();
    walk(Path::new(&tree), &mut files);
    files.sort();
    files.truncate(limit);
    std::fs::create_dir_all(&out).expect("建不了输出目录");

    let mut entries: Vec<Value> = Vec::new();
    let mut failures: Vec<Value> = Vec::new();
    let mut seen: HashMap<String, usize> = HashMap::new();
    let (mut n_glb, mut n_dup, mut n_fail, mut n_norm, mut n_uv, mut n_multi) =
        (0usize, 0usize, 0usize, 0usize, 0usize, 0usize);
    let mut n_rigged = 0usize;
    let (mut n_verts, mut n_tris) = (0u64, 0u64);
    let mut by_cat: HashMap<String, usize> = HashMap::new();

    for f in &files {
        let rel = f
            .strip_prefix(Path::new(&tree))
            .unwrap_or(f)
            .to_string_lossy()
            .replace('\\', "/");
        let raw = match std::fs::read(f) {
            Ok(r) => r,
            Err(e) => {
                failures.push(json!({"path": rel, "error": format!("读文件失败：{e}")}));
                n_fail += 1;
                continue;
            }
        };
        let l = match parse_mesh(&raw) {
            Ok(l) => l,
            Err(e) => {
                failures.push(json!({"path": rel, "error": e}));
                n_fail += 1;
                continue;
            }
        };
        let g = &l.geometry;
        let id = content_id(&raw);
        let file = format!("m_{id}.glb");
        // rigged 出口：骨架解得出才试；失败记入 failures 后回退静态（不降级成
        // 假成功，也不让一份骨架的意外拖死整批）。
        let mut rigged_anim_names: Vec<String> = Vec::new();
        let mut is_rigged = false;
        if !seen.contains_key(&id) {
            let mut written = false;
            if rigged {
                match rigged_glb(Path::new(&tree), &rel, &stem(&rel), &raw, &l) {
                    Some(Ok((bytes, names, skipped))) => {
                        for s in &skipped {
                            eprintln!("  [rigged] {rel}: 跳过 {s}");
                        }
                        if let Err(e) = std::fs::write(Path::new(&out).join(&file), &bytes) {
                            failures.push(json!({
                                "path": rel, "error": format!("写 {file} 失败：{e}")
                            }));
                            n_fail += 1;
                            continue;
                        }
                        rigged_anim_names = names;
                        is_rigged = true;
                        n_glb += 1;
                        n_rigged += 1;
                        written = true;
                    }
                    Some(Err(e)) => {
                        failures.push(json!({
                            "path": rel,
                            "error": format!("rigged 导出失败：{e}（回退静态）"),
                        }));
                    }
                    None => {} // 没有骨架：本来就是静态网格，走原路
                }
            }
            if !written {
                match to_glb(&stem(&rel), &l, &[]) {
                    Ok(bytes) => {
                        if let Err(e) = std::fs::write(Path::new(&out).join(&file), &bytes) {
                            failures
                                .push(json!({"path": rel, "error": format!("写 {file} 失败：{e}")}));
                            n_fail += 1;
                            continue;
                        }
                        n_glb += 1;
                    }
                    Err(e) => {
                        failures.push(json!({"path": rel, "error": e}));
                        n_fail += 1;
                        continue;
                    }
                }
            }
        } else {
            n_dup += 1;
        }
        *seen.entry(id.clone()).or_insert(0) += 1;

        if !g.normals.is_empty() {
            n_norm += 1;
        }
        if l.uv_sets > 0 {
            n_uv += 1;
        }
        if g.submesh_count > 1 {
            n_multi += 1;
        }
        n_verts += g.vertex_count as u64;
        n_tris += g.face_count as u64;

        let gid = maps.gid_by_path.get(&rel.to_lowercase()).copied();
        let grp = gid.and_then(|i| maps.group.get(&i));
        let cat = dir_category(&parent(&rel)).to_string();
        *by_cat.entry(cat.clone()).or_insert(0) += 1;
        let group_kind = gid.and_then(|i| maps.group.get(&i).map(|x| kind_zh(&x.0).to_string()));
        let tags = gid.and_then(|i| maps.tags.get(&i)).cloned().unwrap_or_default();

        entries.push(json!({
            "id": id,
            "glb": file,
            "name": stem(&rel),
            "path": rel,
            "dir": parent(&rel),
            "category": cat,
            "groupKind": group_kind,
            "tags": tags,
            "group": gid,
            "verts": g.vertex_count,
            "tris": g.face_count,
            "slots": g.submesh_count,
            "slotFaces": l.face_counts,
            "normals": !g.normals.is_empty(),
            "uv": l.uv_sets > 0,
            // 还没读懂的字节，如实带上：前端用它说明"为什么没有贴图/动作"
            "leftover": l.middle_leftover,
            "trailing": g.trailing_bytes,
            "rigged": is_rigged,
            "animations": rigged_anim_names,
            "refsTotal": grp.map(|x| x.1).unwrap_or(0),
            "refsLocated": grp.map(|x| x.2).unwrap_or(0),
        }));
    }

    let mut cats: Vec<_> = by_cat.into_iter().collect();
    cats.sort();
    let doc = json!({
        "generated": std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0),
        "stats": {
            "mesh": files.len(), "glb": n_glb, "duplicate": n_dup, "failed": n_fail,
            "rigged": n_rigged,
            "withNormals": n_norm, "withUv": n_uv, "multiSlot": n_multi,
            "vertices": n_verts, "triangles": n_tris,
            "uniqueGlb": seen.len(), "byCategory": cats,
            "db": db, "tree": tree,
        },
        "assets": entries,
        "failures": failures,
    });
    let mp = Path::new(&out).join("manifest.json");
    std::fs::write(&mp, serde_json::to_vec(&doc).expect("manifest 序列化")).expect("写 manifest 失败");
    println!(
        "mesh={} glb={} dup={} fail={} rigged={} normals={} uv={} multiSlot={} verts={} tris={} uniqueGlb={} manifest={}",
        files.len(), n_glb, n_dup, n_fail, n_rigged, n_norm, n_uv, n_multi, n_verts, n_tris,
        seen.len(), mp.display()
    );
}
