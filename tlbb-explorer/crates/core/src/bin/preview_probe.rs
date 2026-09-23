//! 预览覆盖率探针（只读）：把"还能从哪里合法地多出一张图"逐条量出来。
//!
//! 这个程序不写任何文件，只做四件事：
//! 1. 按证据强度给每个资产组分一个候选图（本体／成员／已定位引用／同茎同树），
//!    并真去 `.pak` 里解码一次 —— 只有解出像素才算"能出图"；
//! 2. 复算现行 `asset_cards::make_preview` 的取图规则，查清它到底给出了几张**不同的**图；
//! 3. 用引擎自己的 `path_hash` 反查悬空贴图名，验证"无名贴图能否被证明归属"；
//! 4. 统计非图片资源的规模，说明为什么现在还不能给它们做"结构示意"。
//!
//! 判定底线：哈希对得上才是证据；目录相邻只是线索；尺寸相同什么都不是。

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Record;
use tlbb_core::{jmt1, jpak::Pak, path_hash, payload};

/// 能当预览用的资源类型：`JMT1` 贴图解码后出图；`webp`/`jpeg`/`png` 本身就是浏览器
/// 原生格式，容器里的字节直接交给前端即可，不需要新解码器。
const IMG_TYPES: &str = "'texture','webp','jpeg','png'";

/// 贴图类引用后缀（`refs.kind` 用的就是资源自己的后缀）。
const TEX_KINDS: &[&str] = &[".tga", ".dds", ".png", ".webp", ".jpg", ".jpeg", ".bmp"];

struct Args {
    db: PathBuf,
    root: PathBuf,
    /// 真解码上限：0 表示只统计候选、不碰 `.pak`。
    decode: usize,
    /// 路径哈希反查的名称条数（全库约 1.1 万个悬空名 × 3.7 千个目录）。
    sweep: usize,
}

fn parse() -> Args {
    let mut a = Args {
        db: PathBuf::from("D:/TLGL/.scratch/resources.db"),
        root: PathBuf::from("D:/TLGL"),
        decode: 4000,
        sweep: usize::MAX,
    };
    for arg in std::env::args().skip(1) {
        if let Some((k, v)) = arg.split_once('=') {
            match k {
                "--db" => a.db = PathBuf::from(v),
                "--root" => a.root = PathBuf::from(v),
                "--decode" => a.decode = v.parse().unwrap_or(0),
                "--sweep" => a.sweep = v.parse().unwrap_or(0),
                _ => {}
            }
        }
    }
    a
}

fn scalar(con: &Connection, sql: &str) -> i64 {
    con.query_row(sql, [], |r| r.get::<_, i64>(0)).unwrap_or(0)
}

/// 一个图片资源的最小画像。`path` 为空即"没有路径记录"，这类资源不可能被名字对上。
#[derive(Clone)]
struct Res {
    hash: u64,
    rtype: String,
    dir: String,
    path: Option<String>,
}

/// 文件名去掉后缀，只按字面切，不做任何规范化或翻译。
fn stem_of(s: &str) -> String {
    let base = s.rsplit('/').next().unwrap_or(s);
    base.rsplit('.').skip(1).collect::<Vec<_>>().join(".").to_ascii_lowercase()
}

fn dir_of(s: &str) -> String {
    match s.rfind('/') {
        Some(i) => s[..i].to_string(),
        None => String::new(),
    }
}

fn load_images(con: &Connection) -> HashMap<u64, Res> {
    let sql = format!("SELECT hash, type, dir, path FROM resources WHERE type IN ({IMG_TYPES})");
    let mut st = con.prepare(&sql).expect("prepare resources");
    let mut out = HashMap::new();
    let rows = st
        .query_map([], |r| {
            let h: String = r.get(0)?;
            Ok(Res {
                hash: u64::from_str_radix(&h, 16).unwrap_or(0),
                rtype: r.get::<_, String>(1)?,
                dir: r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                path: r.get::<_, Option<String>>(3)?,
            })
        })
        .expect("query resources");
    for row in rows {
        let r = row.expect("resource row");
        out.insert(r.hash, r);
    }
    out
}

/// 打开全部 `.pak`，索引做成哈希表；真解码要按记录定位字节。
struct Store {
    paks: HashMap<String, Pak>,
    recs: HashMap<u64, (String, Record)>,
}

fn open_store(root: &Path) -> Store {
    let mut paks = HashMap::new();
    let mut recs = HashMap::new();
    if let Ok(es) = std::fs::read_dir(root) {
        for e in es.flatten() {
            let p = e.path();
            if p.extension().map(|x| x != "pak").unwrap_or(true) {
                continue;
            }
            let Some(stem) = p.file_stem() else { continue };
            let name = stem.to_string_lossy().to_string();
            let Ok(pak) = Pak::open(&p) else { continue };
            for rec in pak.records() {
                recs.insert(rec.hash, (name.clone(), rec));
            }
            paks.insert(name, pak);
        }
    }
    Store { paks, recs }
}

/// 真解一次：解出来就返回一句人话（编码 + 尺寸），解不出来就是 `None`。
/// 这是"能出图"的唯一判据 —— 没解出来就不许上卡片。
fn render(store: &Store, r: &Res) -> Option<String> {
    let (pak_name, rec) = store.recs.get(&r.hash)?;
    let pak = store.paks.get(pak_name)?;
    let d = payload::decode(pak, rec).ok()?;
    match r.rtype.as_str() {
        "texture" => {
            let t = jmt1::decode(&d.bytes).ok()?;
            match t.codec {
                jmt1::Codec::Webp => t.webp.map(|w| format!("WEBP {}x{} {}B", t.width, t.height, w.len())),
                c if !t.rgba.is_empty() => Some(format!("{} {}x{}", c.as_str(), t.width, t.height)),
                _ => None,
            }
        }
        other => {
            let (magic, tag): (&[u8], &str) = match other {
                "webp" => (b"RIFF", "WEBP"),
                "jpeg" => (b"\xFF\xD8\xFF", "JPEG"),
                _ => (b"\x89PNG", "PNG"),
            };
            if d.bytes.starts_with(magic) && d.bytes.len() > magic.len() + 16 {
                Some(format!("{tag} {}B", d.bytes.len()))
            } else {
                None
            }
        }
    }
}

#[derive(Default)]
struct Tally {
    groups: usize,
    decoded: usize,
    failed: usize,
    images: HashSet<u64>,
    sample: Vec<String>,
}

/// 带备忘的真解码：同一张图只解一次。
fn pick(
    store: &Store,
    imgs: &HashMap<u64, Res>,
    memo: &mut HashMap<u64, Option<String>>,
    h: u64,
) -> Option<String> {
    if let Some(v) = memo.get(&h) {
        return v.clone();
    }
    let v = imgs.get(&h).and_then(|r| render(store, r));
    memo.insert(h, v.clone());
    v
}

struct Group {
    id: i64,
    hub: u64,
    dir: String,
    kind: String,
}

fn main() {
    let a = parse();
    if !a.db.exists() {
        eprintln!("找不到目录库：{}", a.db.display());
        std::process::exit(2);
    }
    let con = Connection::open_with_flags(
        &a.db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("以只读方式打开目录库");

    let imgs = load_images(&con);
    let named_img: Vec<&Res> = imgs.values().filter(|r| r.path.is_some()).collect();
    let n_groups = scalar(&con, "SELECT count(*) FROM agroups");
    println!(
        "目录库：{n_groups} 个资产组 · {} 个图片资源，其中有路径记录的 {} 个（其余 {} 个连文件名都没有）",
        imgs.len(),
        named_img.len(),
        imgs.len() - named_img.len()
    );

    // ---- 组、成员、引用 -----------------------------------------------------
    let mut groups: Vec<Group> = Vec::new();
    {
        let mut st = con.prepare("SELECT id, hub, dir, kind FROM agroups").expect("prepare agroups");
        for r in st
            .query_map([], |r| {
                let h: String = r.get(1)?;
                Ok(Group {
                    id: r.get(0)?,
                    hub: u64::from_str_radix(&h, 16).unwrap_or(0),
                    dir: r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                    kind: r.get::<_, Option<String>>(3)?.unwrap_or_default(),
                })
            })
            .expect("query agroups")
        {
            groups.push(r.expect("agroup row"));
        }
    }
    let mut members: HashMap<i64, Vec<(u64, Option<String>)>> = HashMap::new();
    {
        let mut st = con
            .prepare("SELECT m.gid, m.hash, r.path FROM amembers m LEFT JOIN resources r ON r.hash = m.hash")
            .expect("prepare amembers");
        for r in st
            .query_map([], |r| {
                let h: String = r.get(1)?;
                Ok((
                    r.get::<_, i64>(0)?,
                    u64::from_str_radix(&h, 16).unwrap_or(0),
                    r.get::<_, Option<String>>(2)?,
                ))
            })
            .expect("query amembers")
        {
            let (gid, h, path) = r.expect("member row");
            members.entry(gid).or_insert_with(Vec::new).push((h, path));
        }
    }
    // 引用边按"谁引用"建表。注意：卡片现在只看代表资源的引用，成员的全部没并进来。
    let mut refs: HashMap<u64, Vec<(String, Option<u64>)>> = HashMap::new();
    {
        let mut st = con.prepare("SELECT from_hash, name, to_hash, kind FROM refs").expect("prepare refs");
        for r in st
            .query_map([], |r| {
                let fh: String = r.get(0)?;
                Ok((
                    u64::from_str_radix(&fh, 16).unwrap_or(0),
                    r.get::<_, String>(1)?,
                    r.get::<_, Option<String>>(2)?,
                    r.get::<_, String>(3)?,
                ))
            })
            .expect("query refs")
        {
            let (fh, name, to, kind) = r.expect("ref row");
            if TEX_KINDS.contains(&kind.as_str()) {
                refs.entry(fh)
                    .or_insert_with(Vec::new)
                    .push((name, to.and_then(|t| u64::from_str_radix(&t, 16).ok())));
            }
        }
    }

    let mut by_stem: HashMap<String, Vec<&Res>> = HashMap::new();
    let mut by_dir: HashSet<String> = HashSet::new();
    for r in named_img.iter().copied() {
        if let Some(p) = &r.path {
            by_stem.entry(stem_of(p)).or_insert_with(Vec::new).push(r);
            by_dir.insert(dir_of(p));
        }
    }

    // ---- 逐级判定：每组只取它能拿到的最强一级 ------------------------------
    let mut level: Vec<(&'static str, i64, u64)> = Vec::new();
    for g in &groups {
        if let Some(r) = imgs.get(&g.hub) {
            level.push(("E1 本体即图片", g.id, r.hash));
            continue;
        }
        let ms = members.get(&g.id).cloned().unwrap_or_default();
        if let Some(m) = ms.iter().find_map(|(h, _)| imgs.get(h)) {
            level.push(("E2 本资产成员", g.id, m.hash));
            continue;
        }
        // E3：走全部成员的引用边（不是只看代表资源），且命中的必须是**有路径**的图片。
        let hit = ms.iter().find_map(|(h, _)| {
            refs.get(h)?.iter().find_map(|(_, to)| {
                to.and_then(|t| imgs.get(&t)).filter(|r| r.path.is_some()).map(|r| r.hash)
            })
        });
        if let Some(h) = hit {
            level.push(("E3 已定位引用", g.id, h));
            continue;
        }
        // E4：成员茎名 == 图片茎名，且图片在本资产目录树内。仍只是线索。
        if !g.dir.is_empty() {
            let own: HashSet<String> = ms.iter().filter_map(|(_, p)| p.as_deref()).map(stem_of).collect();
            let cand: Vec<&Res> = own
                .iter()
                .flat_map(|s| by_stem.get(s).into_iter().flatten().copied())
                .filter(|r| r.dir == g.dir || r.dir.starts_with(&format!("{}/", g.dir)))
                .collect();
            match cand.len() {
                0 => {}
                1 => level.push(("E4 同茎同树(推定)", g.id, cand[0].hash)),
                _ => level.push(("E4x 同茎多候选(不出图)", g.id, cand[0].hash)),
            }
        }
    }

    let store = open_store(&a.root);
    println!("容器：{} 个 .pak · {} 条索引记录", store.paks.len(), store.recs.len());

    // ---- 真解码验证 --------------------------------------------------------
    let mut memo: HashMap<u64, Option<String>> = HashMap::new();
    let mut ok: HashMap<&'static str, Tally> = HashMap::new();
    let mut budget = a.decode;
    for (lab, gid, h) in &level {
        let t = ok.entry(*lab).or_default();
        t.groups += 1;
        if budget == 0 {
            continue;
        }
        budget -= 1;
        match pick(&store, &imgs, &mut memo, *h) {
            Some(desc) => {
                t.decoded += 1;
                t.images.insert(*h);
                if t.sample.len() < 3 {
                    t.sample.push(format!("组 {gid} → {:016x}（{desc}）", h));
                }
            }
            None => t.failed += 1,
        }
    }
    let mut keys: Vec<&&'static str> = ok.keys().collect();
    keys.sort();
    println!("\n[1] 证据分级 · 每组只取最强一级，逐张真解码");
    let mut usable: HashSet<i64> = HashSet::new();
    for k in keys {
        let t = &ok[*k];
        if !k.starts_with("E4x") {
            for s in &t.sample {
                println!("      {s}");
            }
        }
        println!(
            "  {:<22} 组 {:>5} · 解出 {:>5} · 解不出 {:>4} · 不同图 {:>5}",
            k, t.groups, t.decoded, t.failed, t.images.len()
        );
    }
    for (lab, gid, h) in &level {
        if !lab.starts_with("E4x") && memo.get(h).map(|v| v.is_some()).unwrap_or(false) {
            usable.insert(*gid);
        }
    }
    println!(
        "  → 合法可出图组 {} / {n_groups} = {:.2}%（E4x 多候选一律不出图）",
        usable.len(),
        100.0 * usable.len() as f64 / n_groups as f64
    );

    // ---- 复算现行规则：同一张图被重复贴到多少组上 --------------------------
    let mut cur_pick: HashMap<i64, u64> = HashMap::new();
    let mut per_hash: HashMap<u64, Vec<i64>> = HashMap::new();
    let mut dir_rows: HashMap<String, Vec<u64>> = HashMap::new();
    for g in &groups {
        let e = dir_rows.entry(g.dir.clone()).or_insert_with(|| {
            let mut st = con
                .prepare_cached(
                    "SELECT hash FROM resources WHERE type='texture' AND dir=?1 ORDER BY original DESC LIMIT 8",
                )
                .expect("prepare fallback");
            st.query_map([&g.dir], |r| {
                let h: String = r.get(0)?;
                Ok(u64::from_str_radix(&h, 16).unwrap_or(0))
            })
            .expect("query fallback")
            .flatten()
            .collect()
        });
        let mut cand: Vec<u64> = Vec::new();
        if let Some(rs) = refs.get(&g.hub) {
            cand.extend(rs.iter().filter_map(|(_, to)| *to));
        }
        if cand.is_empty() {
            cand.extend(e.iter().cloned());
        }
        for h in cand.into_iter().take(6) {
            if imgs.contains_key(&h) && pick(&store, &imgs, &mut memo, h).is_some() {
                cur_pick.insert(g.id, h);
                per_hash.entry(h).or_insert_with(Vec::new).push(g.id);
                break;
            }
        }
    }
    let mut shared: Vec<(usize, u64)> = per_hash.iter().map(|(h, v)| (v.len(), *h)).collect();
    shared.sort_by(|a, b| b.0.cmp(&a.0));
    println!("\n[2] 现行规则复算（只看代表资源的引用 + 目录精确匹配，取原图最大的一张）");
    println!(
        "  出图组 {} / {n_groups} = {:.2}% · 实际只用到了 {} 张不同的图",
        cur_pick.len(),
        100.0 * cur_pick.len() as f64 / n_groups as f64,
        per_hash.len()
    );
    for (n, h) in shared.iter().take(4) {
        if *n <= 1 {
            break;
        }
        println!(
            "    {:016x} 一张图被贴到 {n} 个组（组 {:?} …）",
            h,
            &per_hash[h][..per_hash[h].len().min(4)]
        );
    }
    let empty: Vec<i64> = groups.iter().filter(|g| g.dir.is_empty()).map(|g| g.id).collect();
    let empty_pick = empty.iter().filter(|gid| cur_pick.contains_key(gid)).count();
    println!(
        "  无目录组 {} 个 · 现行 SQL 不过滤空目录，其中 {empty_pick} 个因此拿到了一张毫不相干的图",
        empty.len()
    );

    // ---- 目录放宽（子目录前缀）--------------------------------------------
    let gset: HashSet<&str> = groups.iter().map(|g| g.dir.as_str()).filter(|d| !d.is_empty()).collect();
    let mut pre_new = 0usize;
    let mut pre_risk = 0usize;
    let mut pre_ex: Vec<String> = Vec::new();
    for g in &groups {
        if g.dir.is_empty() || by_dir.contains(&g.dir) {
            continue;
        }
        let p = format!("{}/", g.dir);
        let hits: Vec<&String> = by_dir.iter().filter(|d| d.starts_with(&p)).collect();
        if hits.is_empty() {
            continue;
        }
        pre_new += 1;
        let collide = hits.iter().any(|d| gset.contains(&d[p.len()..]));
        pre_risk += collide as usize;
        if pre_ex.len() < 3 {
            pre_ex.push(format!("{} → {}", g.dir, hits[0]));
        }
    }
    println!("\n[3] 目录放宽（组目录 → 其子目录）");
    println!("  额外命中组 {pre_new} 个，其中子目录本身是另一个组目录（撞车）{pre_risk} 个");
    for e in pre_ex {
        println!("    例：{e}");
    }
    println!("  原因：有路径的 {} 张图片全在 UI 目录下，世界/角色贴图一条路径都没有。", named_img.len());

    // ---- 悬空贴图名能否被证明：path_hash 反查 ------------------------------
    let mut calib = (0usize, 0usize);
    {
        let mut st = con
            .prepare("SELECT hash, path FROM resources WHERE named=1 AND path IS NOT NULL LIMIT 5000")
            .expect("prepare calib");
        for r in st.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))).expect("calib") {
            let (h, p) = r.expect("calib row");
            calib.0 += 1;
            if path_hash(&p) == u64::from_str_radix(&h, 16).unwrap_or(0) {
                calib.1 += 1;
            }
        }
    }
    println!("\n[4] 悬空贴图名反查（判据：引擎哈希就是虚拟路径的哈希）");
    println!("  判据自校验：{}/{} 条有路径资源满足 path_hash(路径)==哈希", calib.1, calib.0);
    let mut ctrl = (0usize, 0usize);
    {
        let mut st = con
            .prepare("SELECT from_path, name, to_hash FROM refs WHERE kind='.tga' AND to_hash IS NOT NULL")
            .expect("prepare ctrl");
        for r in st
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?)))
            .expect("ctrl")
        {
            let (fp, n, to) = r.expect("ctrl row");
            ctrl.0 += 1;
            if path_hash(&format!("{}/{}", dir_of(&fp), n)) == u64::from_str_radix(&to, 16).unwrap_or(0) {
                ctrl.1 += 1;
            }
        }
    }
    println!(
        "  对照组：{} 条**已经对上**的贴图引用里，用\"引用者所在目录/名字\"能算出正确哈希的有 {} 条 → 同目录假设本身不成立，兜底规则只能算线索",
        ctrl.0, ctrl.1
    );
    let mut names: Vec<String> = con
        .prepare("SELECT DISTINCT name FROM refs WHERE to_hash IS NULL AND kind IN ('.tga','.dds','.png')")
        .expect("prepare sweep")
        .query_map([], |r| r.get(0))
        .expect("sweep")
        .flatten()
        .collect();
    names.sort();
    names.dedup();
    names.truncate(a.sweep);
    let dirs: Vec<String> = con
        .prepare("SELECT DISTINCT dir FROM resources WHERE named=1 AND dir<>''")
        .expect("prepare dirs")
        .query_map([], |r| r.get(0))
        .expect("dirs")
        .flatten()
        .collect();
    let blank: HashSet<u64> = imgs.values().filter(|r| r.path.is_none()).map(|r| r.hash).collect();
    let t0 = std::time::Instant::now();
    let mut found = 0usize;
    let mut ex: Vec<String> = Vec::new();
    for n in &names {
        for d in dirs.iter().map(String::as_str).chain(std::iter::once("")) {
            let p = if d.is_empty() { n.clone() } else { format!("{d}/{n}") };
            if blank.contains(&path_hash(&p)) {
                found += 1;
                if ex.len() < 5 {
                    ex.push(p);
                }
                break;
            }
        }
    }
    println!(
        "  反查：{} 个悬空名 × {} 个已知目录 = {} 次比对，命中 {found}（{:.1}s）",
        names.len(),
        dirs.len() + 1,
        names.len() * (dirs.len() + 1),
        t0.elapsed().as_secs_f64()
    );
    for e in ex {
        println!("    命中 {e}");
    }

    // ---- UI 与未成组的图片资源 --------------------------------------------
    let in_member: HashSet<u64> = members.values().flat_map(|v| v.iter().map(|(h, _)| *h)).collect();
    let ui: Vec<&Group> = groups.iter().filter(|g| g.kind == "ui").collect();
    let ui_ok = ui.iter().filter(|g| usable.contains(&g.id)).count();
    let ungrouped: Vec<u64> = named_img.iter().filter(|r| !in_member.contains(&r.hash)).map(|r| r.hash).collect();
    let mut ug_ok = 0usize;
    for h in ungrouped.iter().take(a.decode) {
        if pick(&store, &imgs, &mut memo, *h).is_some() {
            ug_ok += 1;
        }
    }
    println!("\n[5] UI 与未成组图片资源");
    println!("  kind=ui 的组 {} 个，合法出图 {ui_ok} 个（本体即贴图，无需归属推断）", ui.len());
    println!(
        "  有路径却不属于任何组的图片 {} 个，抽验解出 {ug_ok} 个 → 卡片以\"组\"为单位，这批现在根本没有卡片",
        ungrouped.len()
    );

    // ---- 非图片资源规模 ---------------------------------------------------
    println!("\n[6] 非图片成员规模（含该角色的组数）与可用可视化");
    let mut st = con
        .prepare(
            "SELECT m.role, count(DISTINCT m.gid) FROM amembers m JOIN resources r ON r.hash=m.hash \
             WHERE r.type IN ('mesh','ani','scene','wav','ogg') GROUP BY 1 ORDER BY 2 DESC",
        )
        .expect("prepare roles");
    for r in st.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?))).expect("roles") {
        let (role, n) = r.expect("role row");
        println!("  {role:<10} {n:>5} 组 · 解析器：无 → 顶点/关键帧取不出来，任何\"示意图\"都是编的");
    }
    let no_img = n_groups as usize - usable.len();
    println!(
        "  没有任何合法图片来源的组：{no_img} / {n_groups} = {:.1}%（只能保持类型轮廓占位）",
        100.0 * no_img as f64 / n_groups as f64
    );
}
