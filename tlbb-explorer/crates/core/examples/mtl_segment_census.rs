//! 材质记录分段普查：`.mtl` 字符串表里的「材质名 + 其后贴图」是不是天然分段。
//!
//! 分层贴图现在按 `.mtl` 里贴图的先后顺序分配子网格，这是猜的。这里换一条可核证据：
//! 按 JBCF 字符串顺序切段，每段以一条 `*.mtl`（材质）开头，段内的 `*.tga` 归它，
//! 混合模式取段自己的材质名（含 `effect_add_trans` 才是叠加）。
//! 然后对三份口径与子网格数求一致率：段数、颜色层数、非 pbr 贴图数。
//!
//! 只读：db、pak 全部只读打开，不落任何资源字节。
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --example mtl_segment_census -- --limit 300 --show 8
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jbcf;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::parse_mesh;

fn tail(p: &str) -> String {
    p.rsplit(['/', '\\'])
        .next()
        .unwrap_or(p)
        .to_ascii_lowercase()
}

fn stem_of(p: &str) -> String {
    let t = tail(p);
    match t.rsplit_once('.') {
        Some((s, _)) => s.to_string(),
        None => t,
    }
}

struct Store {
    root: PathBuf,
    paks: HashMap<String, Pak>,
    fails: usize,
}

impl Store {
    /// 按 hash 取字节：容器按名字缓存，同名只开一次。
    fn bytes(&mut self, pak_name: &str, hash: u64) -> Option<Vec<u8>> {
        if !self.paks.contains_key(pak_name) {
            let file = self.root.join(format!("{pak_name}.pak"));
            match Pak::open(&file) {
                Ok(p) => {
                    self.paks.insert(pak_name.to_string(), p);
                }
                Err(e) => {
                    eprintln!("{pak_name} 打不开：{e}");
                    return None;
                }
            }
        }
        let p = self.paks.get(pak_name)?;
        let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
        let raw = payload::decode(p, &rec).ok().map(|x| x.bytes);
        if raw.is_none() {
            self.fails += 1;
        }
        raw
    }
}

/// 一条材质段：材质名、着色器名、颜色图（含 mask）、pbr 图数。
struct Record {
    material: String,
    shaders: Vec<String>,
    textures: Vec<String>,
    pbr: usize,
}

/// 材质名尾巴 → 着色器集合、段数、该段里 mask 贴图数。
type MatStat = (std::collections::BTreeSet<String>, usize, usize);

/// 颜色层数：段内非 mask 贴图之和（pbr 已在分段时单记）。
fn colors_of(records: &[Record]) -> usize {
    records
        .iter()
        .map(|r| {
            r.textures
                .iter()
                .filter(|t| !t.to_ascii_lowercase().contains("mask"))
                .count()
        })
        .sum()
}

fn main() {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let db = std::env::var("TLBB_DB")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join(".scratch/resources.db"));
    let mut limit = 300usize;
    let mut show = 8usize;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--limit" => limit = args.next().unwrap_or_default().parse().unwrap_or(limit),
            "--show" => show = args.next().unwrap_or_default().parse().unwrap_or(show),
            other => eprintln!("未知参数 {other}"),
        }
    }

    let con = Connection::open_with_flags(
        &db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("资源清单打不开");

    // 同名茎的 .mesh：拿它的子网格数当对齐目标。
    let mut mesh_by_stem: HashMap<String, (u64, String)> = HashMap::new();
    let mut mtl_rows: Vec<(u64, String, String)> = Vec::new();
    {
        let mut st = con
            .prepare("SELECT hash, coalesce(pak,''), coalesce(path,'') FROM resources WHERE name LIKE '%.mesh' AND coalesce(pak,'') <> ''")
            .unwrap();
        let rows = st
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })
            .unwrap();
        for row in rows.flatten() {
            let (hex, pak, path) = row;
            if let Ok(h) = u64::from_str_radix(&hex, 16) {
                mesh_by_stem
                    .entry(stem_of(if path.is_empty() { &hex } else { &path }))
                    .or_insert((h, pak));
            }
        }
    }
    {
        let mut st = con
            .prepare("SELECT hash, coalesce(pak,''), coalesce(path,'') FROM resources WHERE name LIKE '%.mtl' AND coalesce(pak,'') <> '' ORDER BY coalesce(path,'')")
            .unwrap();
        let rows = st
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })
            .unwrap();
        for row in rows.flatten() {
            let (hex, pak, path) = row;
            if let Ok(h) = u64::from_str_radix(&hex, 16) {
                mtl_rows.push((h, pak, path));
            }
        }
    }

    let mut store = Store {
        root: root.clone(),
        paks: HashMap::new(),
        fails: 0,
    };

    let mut scanned = 0usize;
    let mut skipped_no_mesh = 0usize;
    let mut rec_eq = 0usize;
    let mut color_eq = 0usize;
    let mut tex_eq = 0usize;
    let mut color_lt = 0usize;
    let mut color_gt = 0usize;
    let mut effect_models = 0usize;
    let mut multi_rec_no_effect = 0usize;
    let mut single_rec_multi_sub = 0usize;
    let mut shader_add = 0usize;
    let mut printed_lt = 0usize;
    let mut printed_gt = 0usize;
    let mut mismatch_lt = 0usize;
    let mut mismatch_gt = 0usize;
    let mut lt_multi_mat = 0usize;
    let mut gt_multi_mat = 0usize;
    let mut lt_dup_texture = 0usize;
    let mut lt_no_color = 0usize;
    let mut lt_no_color_none = 0usize;
    let mut lt_no_color_pbr = 0usize;
    let mut gt_dup_texture = 0usize;
    let mut rows_out: Vec<String> = Vec::new();
    let mut mat_stat: HashMap<String, MatStat> = HashMap::new();
    let mut eq_with_effect = 0usize;
    let mut tot_with_effect = 0usize;
    let mut eq_no_effect = 0usize;
    let mut tot_no_effect = 0usize;
    let mut mask_records = 0usize;
    let mut mask_total = 0usize;
    let mut mask_adjacent = 0usize;
    let mut seq_samples: Vec<String> = Vec::new();
    let mut effect_samples: Vec<(String, Vec<String>)> = Vec::new();

    for (hash, pak, path) in mtl_rows {
        if scanned >= limit {
            break;
        }
        let name = if path.is_empty() {
            format!("{hash:016x}")
        } else {
            path.clone()
        };
        let key = stem_of(&name);
        let Some((mhash, mpak)) = mesh_by_stem.get(&key).cloned() else {
            skipped_no_mesh += 1;
            continue;
        };
        let Some(mtl_raw) = store.bytes(&pak, hash) else {
            continue;
        };
        let Ok(j) = jbcf::parse(&mtl_raw) else {
            continue;
        };
        let Some(mesh_raw) = store.bytes(&mpak, mhash) else {
            continue;
        };
        let Ok(layout) = parse_mesh(&mesh_raw) else {
            continue;
        };
        scanned += 1;

        // 按字符串顺序分段：遇材质名起新段，段内收贴图（pbr 单记，不当颜色层）。
        let mut records: Vec<Record> = Vec::new();
        let mut seq: Vec<&'static str> = Vec::new();
        for s in &j.strings {
            let low = s.text.to_ascii_lowercase();
            match jbcf::role(&s.text) {
                jbcf::Role::Material => {
                    seq.push("M");
                    records.push(Record {
                        material: s.text.clone(),
                        shaders: Vec::new(),
                        textures: Vec::new(),
                        pbr: 0,
                    });
                }
                jbcf::Role::Shader => {
                    seq.push("S");
                    if records.is_empty() {
                        records.push(Record {
                            material: "<段首没有材质名>".to_string(),
                            shaders: Vec::new(),
                            textures: Vec::new(),
                            pbr: 0,
                        });
                    }
                    records.last_mut().unwrap().shaders.push(s.text.clone());
                }
                jbcf::Role::Texture => {
                    seq.push(if low.contains("_pbr") {
                        "P"
                    } else if low.contains("mask") {
                        "K"
                    } else {
                        "T"
                    });
                    if records.is_empty() {
                        records.push(Record {
                            material: "<段首没有材质名>".to_string(),
                            shaders: Vec::new(),
                            textures: Vec::new(),
                            pbr: 0,
                        });
                    }
                    let last = records.last_mut().unwrap();
                    if low.contains("_pbr") {
                        last.pbr += 1;
                    } else {
                        last.textures.push(s.text.clone());
                    }
                }
                _ => {}
            }
        }
        seq_samples.push(format!(
            "{} [{}] 段={} 颜色={} 子网格={}",
            tail(&name),
            seq.join(""),
            records.len(),
            colors_of(&records),
            layout.face_counts.len()
        ));
        // 累计「材质名尾巴 → 着色器集合」：混合模式的证据到底在材质名还是着色器名里。
        for r in &records {
            let key = tail(&r.material).replace(".mtl", "");
            let e = mat_stat
                .entry(key)
                .or_insert_with(|| (std::collections::BTreeSet::new(), 0, 0));
            for sh in &r.shaders {
                e.0.insert(tail(sh));
            }
            e.1 += 1;
            e.2 += r
                .textures
                .iter()
                .filter(|t| t.to_ascii_lowercase().contains("mask"))
                .count();
        }
        let nsub = layout.face_counts.len();
        let tex_all: usize = records.iter().map(|r| r.textures.len()).sum();
        let colors: usize = records
            .iter()
            .map(|r| {
                r.textures
                    .iter()
                    .filter(|t| !t.to_ascii_lowercase().contains("mask"))
                    .count()
            })
            .sum();
        let has_effect = records
            .iter()
            .any(|r| r.material.to_ascii_lowercase().contains("effect_add_trans"));
        if has_effect {
            effect_models += 1;
            tot_with_effect += 1;
            if colors == nsub {
                eq_with_effect += 1;
            }
            // 特效段里带多张颜色图的：记下来看它们是不是「专属图 + 共用光效图」的组合。
            for r in &records {
                if !r.material.to_ascii_lowercase().contains("effect_add_trans") {
                    continue;
                }
                let cs: Vec<String> = r
                    .textures
                    .iter()
                    .filter(|t| !t.to_ascii_lowercase().contains("mask"))
                    .map(|t| tail(t))
                    .collect();
                if cs.len() >= 2 {
                    effect_samples.push((tail(&name), cs));
                }
            }
        } else {
            tot_no_effect += 1;
            if colors == nsub {
                eq_no_effect += 1;
            }
            if records.len() > 1 {
                multi_rec_no_effect += 1;
            }
        }
        // mask 后紧跟颜色图（界面现在就是这条配对规则）在段内的成立数：与段里 mask 总数对比。
        for r in &records {
            let mut masks = 0usize;
            let mut adj = 0usize;
            for (i, t) in r.textures.iter().enumerate() {
                if t.to_ascii_lowercase().contains("mask") {
                    masks += 1;
                    if i + 1 < r.textures.len()
                        && !r.textures[i + 1].to_ascii_lowercase().contains("mask")
                    {
                        adj += 1;
                    }
                }
            }
            mask_records += (masks > 0) as usize;
            mask_total += masks;
            mask_adjacent += adj;
        }
        if records.len() == nsub {
            rec_eq += 1;
        }
        if colors == nsub {
            color_eq += 1;
        } else if colors < nsub {
            color_lt += 1;
        } else {
            color_gt += 1;
        }
        if tex_all == nsub {
            tex_eq += 1;
        }
        // 着色器名里带 add/trans 的份数：这是混合模式的另一条证据来源。
        if records.iter().any(|r| {
            r.shaders
                .iter()
                .any(|sh| sh.to_ascii_lowercase().contains("add"))
                || r.shaders
                    .iter()
                    .any(|sh| sh.to_ascii_lowercase().contains("trans"))
        }) {
            shader_add += 1;
        }
        if records.len() == 1 && nsub > 1 {
            single_rec_multi_sub += 1;
        }
        // 不对齐的份按方向分别摊开：少了多半是「一张图服务多段」，多了多半是第二材质。
        if colors != nsub {
            let mut names_in_file: HashMap<String, usize> = HashMap::new();
            for r in &records {
                for t in &r.textures {
                    if !t.to_ascii_lowercase().contains("mask") {
                        *names_in_file.entry(tail(t)).or_insert(0) += 1;
                    }
                }
            }
            let dup = names_in_file.values().filter(|&&n| n > 1).count();
            if colors < nsub {
                mismatch_lt += 1;
                if colors == 0 {
                    lt_no_color += 1;
                    if tex_all == 0 {
                        lt_no_color_none += 1;
                    } else {
                        lt_no_color_pbr += 1;
                    }
                }
                if records.len() > 1 {
                    lt_multi_mat += 1;
                }
                if dup > 0 {
                    lt_dup_texture += 1;
                }
            } else {
                mismatch_gt += 1;
                if records.len() > 1 {
                    gt_multi_mat += 1;
                }
                if dup > 0 {
                    gt_dup_texture += 1;
                }
            }
            let dir = if colors < nsub { "少" } else { "多" };
            let want = if colors < nsub { &mut printed_lt } else { &mut printed_gt };
            if *want < show {
                let mut block = format!(
                    "不对齐（颜色{dir}）：{} 段={} 颜色={} 子网格={} 重名图={dup}",
                    tail(&name),
                    records.len(),
                    colors,
                    nsub
                );
                for r in &records {
                    block.push_str(&format!(
                        "\n   段 [{}] 颜色 {} 张：{}",
                        tail(&r.material).replace(".mtl", ""),
                        r.textures
                            .iter()
                            .filter(|t| !t.to_ascii_lowercase().contains("mask"))
                            .count(),
                        r.textures
                            .iter()
                            .map(|t| tail(t))
                            .collect::<Vec<_>>()
                            .join(", ")
                    ));
                }
                rows_out.push(block);
                *want += 1;
            }
        }
    }

    for b in &rows_out {
        println!("{b}");
    }
    println!("---");
    println!(
        "同名 .mesh 缺失而跳过：{skipped_no_mesh}；解出网格+材质的份数：{scanned}；取字节失败：{}",
        store.fails
    );
    println!("材质段数 == 子网格数：{rec_eq}/{scanned}");
    println!("颜色层数（去 mask）== 子网格数：{color_eq}/{scanned}，少 {color_lt}、多 {color_gt}");
    println!("非 pbr 贴图数 == 子网格数：{tex_eq}/{scanned}");
    println!("含 effect_add_trans 的份数：{effect_models}/{scanned}");
    println!("多段但无 effect 的份数：{multi_rec_no_effect}/{scanned}");
    println!("单段却多子网格的份数：{single_rec_multi_sub}/{scanned}");
    println!(
        "颜色层数==子网格数：含 effect {eq_with_effect}/{tot_with_effect}；不含 effect {eq_no_effect}/{tot_no_effect}"
    );
    let mismatch = mismatch_lt + mismatch_gt;
    if mismatch > 0 {
        println!(
            "不对齐 {mismatch}/{scanned}：颜色少于段 {mismatch_lt}（其中完全没有颜色图 {lt_no_color}：零贴图 {lt_no_color_none}、只有 pbr {lt_no_color_pbr}；多材质 {lt_multi_mat}、有重名图 {lt_dup_texture}）；颜色多于段 {mismatch_gt}（多材质 {gt_multi_mat}、有重名图 {gt_dup_texture}）"
        );
    }
    println!("段里出现过 mask 的段数：{mask_records}；mask 贴图总数 {mask_total}，其中后面紧跟一张非 mask 的 {mask_adjacent}");
    println!("—— 材质名尾巴 → 着色器（按段数排序，前 20）——");
    let mut mats: Vec<(&String, &MatStat)> = mat_stat.iter().collect();
    mats.sort_by_key(|(_, v)| std::cmp::Reverse(v.1));
    for (name, (shaders, count, masks)) in mats.iter().take(20) {
        println!(
            "  {name}  段数={count}  该段里 mask 贴图={masks}  着色器={:?}",
            shaders.iter().collect::<Vec<_>>()
        );
    }
    println!("有 add/trans 着色器的份数：{shader_add}/{scanned}");
    // 字符串表里角色先后顺序的分布：M=材质 T=颜色 P=pbr K=mask S=着色器。
    let mut pat: HashMap<String, usize> = HashMap::new();
    for s in &seq_samples {
        let Some((_, rest)) = s.split_once('[') else {
            continue;
        };
        let Some((seq, _)) = rest.split_once(']') else {
            continue;
        };
        *pat.entry(seq.to_string()).or_insert(0) += 1;
    }
    let mut pat: Vec<_> = pat.into_iter().collect();
    pat.sort_by_key(|(_, n)| std::cmp::Reverse(*n));
    println!("—— 字符串表角色顺序分布（前 15）——");
    for (seq, n) in pat.iter().take(15) {
        println!("  {n:>5}  {seq}");
    }
    // 特效段里多张颜色图：按「这个图名在多少个模型的特效段里出现」排。
    // 专属图（只出现 1 次）多半是模型自己的花纹；跨模型重复的（lf012 这类）更像共用光效。
    if !effect_samples.is_empty() {
        let mut occ: HashMap<&str, usize> = HashMap::new();
        for (_, cs) in &effect_samples {
            for c in cs {
                *occ.entry(c.as_str()).or_insert(0) += 1;
            }
        }
        println!("—— 特效段里多张颜色图的组合（前 10，括号是出现模型数）——");
        for (m, cs) in effect_samples.iter().take(10) {
            let parts: Vec<String> = cs
                .iter()
                .map(|c| format!("{c}({})", occ.get(c.as_str()).copied().unwrap_or(0)))
                .collect();
            println!("  {m}: {}", parts.join(", "));
        }
        let multi = effect_samples.len();
        let first_unique = effect_samples
            .iter()
            .filter(|(_, cs)| occ.get(cs[0].as_str()).copied().unwrap_or(0) == 1)
            .count();
        let any_shared = effect_samples
            .iter()
            .filter(|(_, cs)| cs.iter().skip(1).any(|c| occ.get(c.as_str()).copied().unwrap_or(0) > 1))
            .count();
        println!(
            "特效段多颜色组合 {multi} 例：第一张只在 1 个模型出现 {first_unique} 例；后续图里有跨模型共用图的 {any_shared} 例"
        );
    }
}
