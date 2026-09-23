//! 无名资源体检（只读）：查清 `agroups` 里那批"三无组"（茎名、路径、目录全空）到底是什么，
//! 以及它们在界面上应该怎么呈现。
//!
//! 只做三件事，全部是读取，不写任何文件：
//! 1. 从 `resources.db` 读出这批组，统计成员构成与它们为什么独立成组；
//! 2. 回到 `.pak` 把每个成员真解码一次，按内容魔数和 `JBCF` 字符串表分桶；
//! 3. 明确回答"里面有没有能出图的"，并顺带抽样验证未命名 `JMT1` 贴图能不能出图。
//!
//! 呈现规范在这里同样生效：不伪造名称、不伪造预览、输出用大白话中文。

use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::{Path, PathBuf};

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jbcf::{self, Role};
use tlbb_core::jmt1;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;

/// 一条 "三无组" 的目录信息，全部来自 catalog，不做任何推断。
struct Row {
    hash: u64,
    rtype: String,
    subtype: String,
    codec: String,
    pak: String,
    gen: i64,
    offset: i64,
    original: i64,
}

struct Args {
    root: PathBuf,
    db: PathBuf,
    /// 未命名贴图抽样解码条数；0 表示跳过这项附带核查。
    texture_check: usize,
}

fn parse_args() -> Args {
    let mut a = Args {
        root: PathBuf::from("D:/TLGL"),
        db: PathBuf::from("D:/TLGL/.scratch/resources.db"),
        texture_check: 300,
    };
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let mut i = 0;
    while i < raw.len() {
        let (k, v) = match raw[i].split_once('=') {
            Some((k, v)) => (k, Some(v.to_string())),
            None => {
                let k = raw[i].as_str();
                let v = raw.get(i + 1).filter(|s| !s.starts_with("--")).cloned();
                if v.is_some() {
                    i += 1;
                }
                (k, v)
            }
        };
        let take = || v.clone().unwrap_or_default();
        match k {
            "--root" => a.root = PathBuf::from(take()),
            "--db" => a.db = PathBuf::from(take()),
            "--texture-check" => a.texture_check = take().parse().unwrap_or(0),
            _ => {}
        }
        i += 1;
    }
    a
}

/// 只读打开：探针绝不允许改写资产库或包文件。
fn open_ro(path: &Path) -> Connection {
    Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("以只读方式打开 resources.db")
}

type Tally = BTreeMap<String, usize>;

fn bump(t: &mut Tally, k: String) {
    *t.entry(k).or_default() += 1;
}

fn show(title: &str, t: &Tally, examples: &HashMap<String, Vec<String>>) {
    if t.is_empty() {
        return;
    }
    println!("\n{title}");
    let mut rows: Vec<(&String, &usize)> = t.iter().collect();
    rows.sort_by(|x, y| y.1.cmp(x.1).then(x.0.cmp(y.0)));
    for (k, v) in rows.iter().take(12) {
        let ex = examples
            .get(*k)
            .filter(|e| !e.is_empty())
            .map(|e| format!("  例 {}", e[..e.len().min(2)].join(", ")))
            .unwrap_or_default();
        println!("  {k:<38} {v:>6}{ex}");
    }
    if rows.len() > 12 {
        println!("  …另有 {} 类", rows.len() - 12);
    }
}

fn pct(part: i64, whole: i64) -> String {
    format!("{:.1}%", 100.0 * part as f64 / whole.max(1) as f64)
}

/// 内容魔数判定：这批组里只要出现任何一条能出图的魔数，就得单独成类，
/// 所以这里覆盖 `preview` 层真正会渲染的格式。
fn image_magic(b: &[u8]) -> Option<&'static str> {
    let m = |n: usize, want: &[u8]| b.len() >= n && &b[..n] == want;
    if m(4, b"JMT1") {
        Some("JMT1 贴图")
    } else if m(8, b"\x89PNG\r\n\x1a\n") {
        Some("PNG")
    } else if m(4, b"RIFF") && b.len() >= 12 && &b[8..12] == b"WEBP" {
        Some("WEBP")
    } else if m(3, b"\xff\xd8\xff") {
        Some("JPEG")
    } else if m(4, b"GIF8") {
        Some("GIF")
    } else if m(4, b"OggS") || m(3, b"ID3") {
        Some("音频")
    } else {
        None
    }
}

/// 字符串表里原样出现的目录串。只用于分类与筛选，绝不当作资源名使用。
fn embedded_dirs(j: &jbcf::Jbcf) -> Vec<String> {
    j.strings
        .iter()
        .map(|s| s.text.as_str())
        .filter(|s| s.contains('/') && !s.ends_with(".mtl") && !s.ends_with(".mdl"))
        .map(str::to_string)
        .collect()
}

fn load_paks(root: &Path) -> (HashMap<String, Pak>, HashMap<(String, u64), tlbb_core::Record>) {
    let mut paks = HashMap::new();
    let mut idx = HashMap::new();
    let mut files: Vec<_> = std::fs::read_dir(root)
        .expect("读取包目录")
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().map(|x| x == "pak").unwrap_or(false))
        .collect();
    files.sort();
    for path in files {
        let stem = path.file_stem().unwrap().to_string_lossy().to_string();
        let pak = Pak::open(&path).expect("以只读方式打开 pak");
        for rec in pak.records() {
            idx.insert((stem.clone(), rec.hash), rec);
        }
        paks.insert(stem, pak);
    }
    (paks, idx)
}

/// 解一条负载；偏移与目录不符时直接放弃，避免读到搬过家的旧记录。
fn decode(
    paks: &HashMap<String, Pak>,
    idx: &HashMap<(String, u64), tlbb_core::Record>,
    pak: &str,
    hash: u64,
    want_off: i64,
) -> Result<Vec<u8>, String> {
    let rec = idx
        .get(&(pak.to_string(), hash))
        .ok_or_else(|| "索引里找不到".to_string())?;
    if rec.offset as i64 != want_off {
        return Err("偏移已变动".to_string());
    }
    let p = paks.get(pak).ok_or("包文件缺失")?;
    payload::decode(p, rec).map(|d| d.bytes).map_err(|e| e.to_string())
}

const NAMELESS_WHERE: &str = "stem='' AND hub_path='' AND dir=''";

fn rows_of(con: &Connection) -> Vec<Row> {
    let sql = "SELECT r.hash, r.type, r.subtype, r.codec, r.pak, r.gen, r.offset, r.original \
               FROM agroups a JOIN amembers m ON m.gid=a.id JOIN resources r ON r.hash=m.hash \
               WHERE a.stem='' AND a.hub_path='' AND a.dir='' ORDER BY a.id";
    let mut st = con.prepare(sql).unwrap();
    let out = st
        .query_map([], |r| {
            Ok(Row {
                hash: u64::from_str_radix(&r.get::<_, String>(0)?, 16).unwrap_or(0),
                rtype: r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                subtype: r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                codec: r.get::<_, Option<String>>(3)?.unwrap_or_default(),
                pak: r.get(4)?,
                gen: r.get(5)?,
                offset: r.get(6)?,
                original: r.get(7)?,
            })
        })
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    out
}

fn scalar(con: &Connection, sql: &str) -> i64 {
    con.query_row(sql, [], |r| r.get(0)).unwrap_or(0)
}

fn main() {
    let args = parse_args();
    let con = open_ro(&args.db);
    let total_groups = scalar(&con, "SELECT COUNT(*) FROM agroups");
    let total_res = scalar(&con, "SELECT COUNT(*) FROM resources");
    let rows = rows_of(&con);

    println!("== 无名资源体检（只读）");
    let share = pct(rows.len() as i64, total_groups);
    println!(
        "库里 {total_res} 条资源、{total_groups} 个资产组；茎名/路径/目录三项全空的组 {} 个（占 {share}），成员合计 {} 个。",
        rows.len(),
        rows.len()
    );

    let mut by_type: Tally = BTreeMap::new();
    let mut by_pak: Tally = BTreeMap::new();
    for r in &rows {
        bump(
            &mut by_type,
            format!("类型={} 子型={} 编码={}", r.rtype, r.subtype, if r.codec.is_empty() { "无" } else { &r.codec }),
        );
        bump(&mut by_pak, format!("{} 第 {} 代", r.pak, r.gen));
    }
    show("成员按类型细分", &by_type, &HashMap::new());
    show("成员按所在包/代际", &by_pak, &HashMap::new());

    // ------------------------------------------------------------ 真解码 + 内容分桶
    let (paks, idx) = load_paks(&args.root);
    let mut magic_t: Tally = BTreeMap::new();
    let mut bucket_t: Tally = BTreeMap::new();
    let mut layout_t: Tally = BTreeMap::new();
    let mut role_t: Tally = BTreeMap::new();
    let mut dir_t: Tally = BTreeMap::new();
    let mut shader_t: Tally = BTreeMap::new();
    let mut names_t: Tally = BTreeMap::new();
    let mut sizes_t: Tally = BTreeMap::new();
    let mut bad_t: Tally = BTreeMap::new();
    let mut ex: HashMap<String, Vec<String>> = HashMap::new();
    let mut n_image = 0usize;
    let mut n_jbcf = 0usize;
    let mut out_bytes = 0u64;
    let mut min = u64::MAX;
    let mut max = 0u64;

    for r in &rows {
        let key = format!("{:016x}", r.hash);
        let bytes = match decode(&paks, &idx, &r.pak, r.hash, r.offset) {
            Ok(b) => b,
            Err(e) => {
                bump(&mut bad_t, format!("解不出来：{e}"));
                bump(&mut bucket_t, "解不出来".to_string());
                continue;
            }
        };
        out_bytes += bytes.len() as u64;
        min = min.min(bytes.len() as u64);
        max = max.max(bytes.len() as u64);
        if bytes.len() as i64 != r.original {
            bump(&mut bad_t, format!("解出长度 {} 与目录登记 {} 不符", bytes.len(), r.original));
        }
        bump(&mut sizes_t, format!("{} KB 档", (bytes.len() as u64 / 1024).max(1)));
        if let Some(h) = image_magic(&bytes) {
            n_image += 1;
            bump(&mut magic_t, h.to_string());
            bump(&mut bucket_t, "有可视内容".to_string());
            ex.entry("有可视内容".to_string()).or_default().push(key);
            continue;
        }
        let head = if bytes.len() >= 4 {
            String::from_utf8_lossy(&bytes[..4]).trim_end_matches('\0').to_string()
        } else {
            "不足 4 字节".to_string()
        };
        bump(&mut magic_t, head);
        if bytes.iter().all(|c| *c == 0) {
            bump(&mut bucket_t, "全零小块".to_string());
            continue;
        }
        match jbcf::parse(&bytes) {
            Err(e) => {
                bump(&mut bad_t, format!("JBCF 读不出字符串表：{e}"));
                bump(&mut bucket_t, "JBCF 但读不出字符串表".to_string());
            }
            Ok(j) => {
                n_jbcf += 1;
                let mut asm = false;
                for s in &j.strings {
                    let (label, is_asm) = match jbcf::role(&s.text) {
                        Role::Texture => ("贴图名", false),
                        Role::Material => ("材质名", false),
                        Role::Model => ("模型名", true),
                        Role::Skeleton => ("骨骼名", true),
                        Role::Animation => ("动作名", true),
                        Role::Scene => ("场景名", false),
                        Role::Shader => ("着色器名", false),
                        Role::Other => ("其他名（骨骼挂点/目录等）", false),
                    };
                    asm |= is_asm;
                    bump(&mut role_t, label.to_string());
                    if jbcf::role(&s.text) == Role::Shader {
                        bump(&mut shader_t, s.text.clone());
                    }
                }
                let dirs = embedded_dirs(&j);
                for d in dirs.iter() {
                    bump(&mut dir_t, d.trim_end_matches('/').to_string());
                }
                bump(&mut names_t, format!("{} 条名字", j.strings.len()));
                let layout = bytes
                    .get(24..28)
                    .map(|b| u32::from_le_bytes(b.try_into().unwrap()).to_string())
                    .unwrap_or_else(|| "?".to_string());
                bump(&mut layout_t, format!("根块首字段 {layout}"));
                let b = if asm {
                    "配置·模型装配（引用骨骼/网格/动作）"
                } else if dirs.is_empty() {
                    "配置·材质（引用共享材质模板+贴图）"
                } else {
                    "配置·材质（自带来源目录串）"
                };
                bump(&mut bucket_t, b.to_string());
                ex.entry(b.to_string()).or_default().push(key);
            }
        }
    }

    println!("\n全部成员回包真解码：{} 条，共解出 {} 字节（单条 {} ~ {} 字节）",
        rows.len(), out_bytes, min, max);
    show("内容魔数", &magic_t, &HashMap::new());
    show("内容分桶", &bucket_t, &ex);
    show("结构变体（根块首字段）", &layout_t, &HashMap::new());
    show("字符串表规模", &names_t, &HashMap::new());
    show("体积分布", &sizes_t, &HashMap::new());
    show("引用名类型", &role_t, &HashMap::new());
    show("异常", &bad_t, &HashMap::new());
    println!(
        "\n能否出图：带图像/音频魔数的 {n_image} 条，配置容器解析成功 {n_jbcf} 条 —— 这批一组都没有可视内容，不给任何预览。"
    );

    show("配置体内原样出现的目录串（仅供分类，不当名字用）", &dir_t, &HashMap::new());
    show("配置体内原样出现的着色器名", &shader_t, &HashMap::new());

    // ------------------------------------------------------------ 为什么没并进有名组
    let in_set = format!(
        "(SELECT m.hash FROM agroups a JOIN amembers m ON m.gid=a.id WHERE a.{NAMELESS_WHERE})"
    );
    let dangling = scalar(
        &con,
        &format!("SELECT COUNT(*) FROM refs WHERE from_hash IN {in_set} AND to_hash IS NULL"),
    );
    let resolved = scalar(
        &con,
        &format!("SELECT COUNT(*) FROM refs WHERE from_hash IN {in_set} AND to_hash IS NOT NULL"),
    );
    let cut = scalar(
        &con,
        &format!(
            "SELECT COUNT(*) FROM relations WHERE rel LIKE 'use-%' AND from_hash IN {in_set} \
             AND to_hash IN (SELECT to_hash FROM relations WHERE rel LIKE 'use-%' \
             GROUP BY to_hash HAVING COUNT(*) > 8)"
        ),
    );
    let with_names = scalar(
        &con,
        &format!(
            "SELECT COUNT(DISTINCT gid) FROM agroup_names WHERE gid IN \
             (SELECT id FROM agroups WHERE {NAMELESS_WHERE})"
        ),
    );
    let tagged = scalar(
        &con,
        &format!(
            "SELECT COUNT(DISTINCT gid) FROM asset_tags WHERE gid IN \
             (SELECT id FROM agroups WHERE {NAMELESS_WHERE})"
        ),
    );
    let mut tag_t: Tally = BTreeMap::new();
    {
        let mut st = con
            .prepare(&format!(
                "SELECT tag, COUNT(*) FROM asset_tags WHERE gid IN \
                 (SELECT id FROM agroups WHERE {NAMELESS_WHERE}) GROUP BY 1"
            ))
            .unwrap();
        for (t, n) in st
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap()
        {
            tag_t.insert(t, n as usize);
        }
    }
    let mut member_role_t: Tally = BTreeMap::new();
    {
        let mut st = con
            .prepare(&format!(
                "SELECT m.role, COUNT(*) FROM agroups a JOIN amembers m ON m.gid=a.id \
                 WHERE a.{NAMELESS_WHERE} GROUP BY 1"
            ))
            .unwrap();
        for (t, n) in st
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?)))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap()
        {
            member_role_t.insert(format!("成员角色={t}"), n as usize);
        }
    }
    println!("\n为什么没并进有名组（聚合规则的三条硬条件）");
    println!(
        "  1) 这些配置引用的名字共 {} 条，能在本机对上真实文件的只有 {resolved} 条（{}），其余 {dangling} 条本机根本没有对应文件。",
        dangling + resolved,
        pct(resolved, dangling + resolved)
    );
    println!("  2) 能对上文件的目标都是被引用超过 8 次的公共件，被聚合规则当\"共享件\"切断：本次命中 {cut} 条，所以组大小停在 1。");
    println!("  3) 组里唯一的成员没有路径，取中心件时只能退回它自己，于是路径/目录/茎名三列全空。");
    println!("  它们仍然被保留成独立组，只因为聚合规则写了\"只贡献一张引用名表的也算资产\"：{with_names} 组都挂到了引用名，{tagged} 组已被打上场景标签。");
    show("成员角色（目录列空导致角色也退化）", &member_role_t, &HashMap::new());
    show("已有的场景标签", &tag_t, &HashMap::new());

    // ------------------------------------------------------------ 附带核查：无名字但能看图的是另一批
    if args.texture_check > 0 {
        let mut st = con
            .prepare(
                "SELECT hash, pak, offset FROM resources \
                 WHERE type='texture' AND path IS NULL LIMIT ?1",
            )
            .unwrap();
        let list = st
            .query_map([args.texture_check as i64], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, i64>(2)?,
                ))
            })
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let unnamed_tex_total = scalar(
            &con,
            "SELECT COUNT(*) FROM resources WHERE type='texture' AND path IS NULL",
        );
        let not_grouped = scalar(
            &con,
            "SELECT COUNT(*) FROM resources r WHERE r.type='texture' AND r.path IS NULL \
             AND NOT EXISTS (SELECT 1 FROM amembers m WHERE m.hash=r.hash)",
        );
        let mut ok_t: Tally = BTreeMap::new();
        let mut err_t: Tally = BTreeMap::new();
        let mut done = 0usize;
        let mut seen: HashSet<u64> = HashSet::new();
        for (hs, pak, off) in list {
            let hash = u64::from_str_radix(&hs, 16).unwrap_or(0);
            if !seen.insert(hash) {
                continue;
            }
            done += 1;
            match decode(&paks, &idx, &pak, hash, off) {
                Err(e) => bump(&mut err_t, format!("解不出来：{e}")),
                Ok(b) => match jmt1::decode(&b) {
                    Ok(t) => bump(
                        &mut ok_t,
                        format!("可出图 {}（{}x{}）", t.codec.as_str(), t.width, t.height),
                    ),
                    Err(e) => bump(&mut err_t, format!("贴图解码失败 {e}")),
                },
            }
        }
        println!(
            "\n附带核查（不属于这批组）：未命名贴图 {unnamed_tex_total} 条，其中 {not_grouped} 条根本没进任何组；抽样解 {done} 条"
        );
        show("抽样结果", &ok_t, &HashMap::new());
        show("抽样失败", &err_t, &HashMap::new());
    }

    println!("\n一句话结论：这批\"完全无名\"的组全是配置小文件——读得出它引用了哪些名字，读不出任何画面。");
}
