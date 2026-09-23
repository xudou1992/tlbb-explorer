//! `view` —— 资源查看器（只读，不写任何文件）。
//!
//! # 这是浏览器的命令行形态
//!
//! 拿一个资源名（或 hash），把它解出来，用**人能看懂的方式**打印它是什么：
//!
//! ```text
//! view.exe --name=w1351_pets_lianyishou_b5.ske
//! view.exe --name=w1351_smeh_shandongkou_001.mtl
//! view.exe --hash=4e161e3ccde3c964
//! view.exe --name=w1351_nan.mdl --png-out=D:/out      # 顺带导出贴图 PNG
//! ```
//!
//! # 三条纪律（与项目原则一致）
//!
//! 1. **解不出就说解不出**，不猜、不拿同类资源顶。
//! 2. **缺什么显示什么**：材质引用对不上的贴图，显示「缺」，不显示「可能是什么」。
//! 3. **名称一律客户端原文**，不翻译、不编显示名。

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Record;
use tlbb_core::preview::{summary, SlotSummary, ViewBody};
use tlbb_core::{jbcf, jmt1, jpak::Pak, payload};

struct Args {
    db: PathBuf,
    root: PathBuf,
    /// 按名字查（客户端原文，可带或不带扩展名）。
    name: Option<String>,
    /// 按 hash 查（16 位十六进制）。
    hash: Option<u64>,
    /// 列出某类型的资源（分页）。
    list_type: Option<String>,
    limit: usize,
    /// 导出贴图为 PNG 的目录；空则不出图。
    png_out: Option<PathBuf>,
    /// 列出多少个候选（按名字模糊查时）。
    cands: usize,
    /// dump 前 N 字节的十六进制（0 = 不 dump）。
    dump: usize,
}

fn parse() -> Args {
    let mut a = Args {
        db: PathBuf::from("D:/TLGL/.scratch/resources.db"),
        root: PathBuf::from("D:/TLGL"),
        name: None,
        hash: None,
        list_type: None,
        limit: 20,
        png_out: None,
        cands: 20,
        dump: 0,
    };
    for arg in std::env::args().skip(1) {
        let (k, v) = match arg.split_once('=') {
            Some(kv) => kv,
            None => (arg.as_str(), ""),
        };
        match k {
            "--db" => a.db = PathBuf::from(v),
            "--root" => a.root = PathBuf::from(v),
            "--name" => a.name = Some(v.to_string()),
            "--hash" => a.hash = u64::from_str_radix(v, 16).ok(),
            "--type" => a.list_type = Some(v.to_string()),
            "--limit" => a.limit = v.parse().unwrap_or(20),
            "--png-out" => a.png_out = Some(PathBuf::from(v)),
            "--cands" => a.cands = v.parse().unwrap_or(20),
            "--dump" => a.dump = v.parse().unwrap_or(0),
            _ => {}
        }
    }
    a
}

/// 一个资源在目录里的记录。
#[derive(Clone, Debug)]
struct Res {
    hash: u64,
    name: String,
    path: String,
    rtype: String,
    ext: String,
    codec: String,
    width: i64,
    height: i64,
    pak: String,
    offset: i64,
    original: i64,
}

fn open_db(path: &Path) -> Connection {
    Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("只读打开 resources.db")
}

const RES_COLS: &str = "hash, coalesce(name,''), coalesce(path,''), coalesce(type,''), \
                        coalesce(ext,''), coalesce(codec,''), coalesce(width,0), coalesce(height,0), \
                        coalesce(pak,''), coalesce(offset,0), coalesce(original,0)";

fn row_to_res(r: &rusqlite::Row) -> rusqlite::Result<Res> {
    let h: String = r.get(0)?;
    Ok(Res {
        hash: u64::from_str_radix(&h, 16).unwrap_or(0),
        name: r.get(1)?,
        path: r.get(2)?,
        rtype: r.get(3)?,
        ext: r.get(4)?,
        codec: r.get(5)?,
        width: r.get(6)?,
        height: r.get(7)?,
        pak: r.get(8)?,
        offset: r.get(9)?,
        original: r.get(10)?,
    })
}

/// 打开所有 `.pak` 并建 hash → (pak名, 记录) 索引。
fn open_paks(root: &Path) -> (HashMap<String, Pak>, HashMap<u64, (String, Record)>) {
    let mut paks = HashMap::new();
    let mut recs = HashMap::new();
    let Ok(es) = std::fs::read_dir(root) else {
        return (paks, recs);
    };
    for e in es.flatten() {
        let p = e.path();
        if p.extension().map(|x| x != "pak").unwrap_or(true) {
            continue;
        }
        let Some(stem) = p.file_stem() else { continue };
        let key = stem.to_string_lossy().to_string();
        let Ok(pak) = Pak::open(&p) else { continue };
        for rec in pak.records() {
            recs.insert(rec.hash, (key.clone(), rec));
        }
        paks.insert(key, pak);
    }
    (paks, recs)
}

/// 把名字对上 hash。返回 `(hash, 已解析?)`。
fn resolve_name(con: &Connection, name: &str) -> Option<u64> {
    let n: Option<String> = con
        .query_row(
            "select hash from resources where name=? limit 1",
            [name],
            |r| r.get(0),
        )
        .ok();
    n.and_then(|s| u64::from_str_radix(&s, 16).ok())
}

fn main() {
    let a = parse();
    let con = open_db(&a.db);
    let (paks, recs) = open_paks(&a.root);

    // ---------------- 列类型 ----------------
    if let Some(t) = &a.list_type {
        println!("列出 type = {t}（前 {} 条）：", a.limit);
        let sql = format!(
            "select {RES_COLS} from resources where type=?1 \
             order by case when coalesce(name,'')<>'' then 0 else 1 end, name limit ?2"
        );
        let mut st = con.prepare(&sql).expect("prepare");
        let rows = st.query_map(rusqlite::params![t, a.limit as i64], row_to_res).expect("query");
        for r in rows.flatten() {
            let shown = if r.name.is_empty() { "<无名>" } else { &r.name };
            println!(
                "  {:016x}  {:<46} {:>5}x{:<5} {:>8}B  {}",
                r.hash, shown, r.width, r.height, r.original, r.pak
            );
        }
        return;
    }

    // ---------------- 定位目标 ----------------
    let (target, how) = if let Some(h) = a.hash {
        let sql = format!("select {RES_COLS} from resources where hash=?1");
        let got = con
            .query_row(&sql, [format!("{h:016x}")], row_to_res)
            .ok();
        (got, format!("hash {h:016x}"))
    } else if let Some(n) = &a.name {
        // 先精确，再模糊
        let sql = format!("select {RES_COLS} from resources where name=?1 limit 1");
        let exact = con.query_row(&sql, [n.as_str()], row_to_res).ok();
        if exact.is_some() {
            (exact, format!("名字 {n}"))
        } else {
            let sql = format!(
                "select {RES_COLS} from resources where name like ?1 \
                 order by length(name) limit 1"
            );
            let like = format!("%{n}%");
            let got = con.query_row(&sql, [like], row_to_res).ok();
            if got.is_none() {
                eprintln!("没有找到与「{n}」匹配的资源。");
                eprintln!("提示：用 --type=mesh 之类先列一下有哪些，或换个更长、更独特的片段。");
                std::process::exit(2);
            }
            (got, format!("名字含 {n}（模糊匹配）"))
        }
    } else {
        eprintln!("用法：");
        eprintln!("  view --name=<客户端原文名>       按名字查（可模糊）");
        eprintln!("  view --hash=<16位hex>           按 hash 查");
        eprintln!("  view --type=<mesh|texture|ani>  列某一类");
        eprintln!("  view --name=... --png-out=<目录>  顺带导出贴图 PNG");
        std::process::exit(1);
    };

    let Some(Res { .. }) = target else {
        eprintln!("没找到资源。");
        std::process::exit(2);
    };
    let res = target.unwrap();

    // ---------------- 头部信息 ----------------
    println!("════════════════════════════════════════════════════════════════");
    println!("资源：{}", if res.name.is_empty() { "<无名>" } else { &res.name });
    println!("  hash       {:016x}", res.hash);
    println!("  类型       {} {}", res.rtype, res.ext);
    if !res.path.is_empty() {
        println!("  路径       {}", res.path);
    } else {
        println!("  路径       （客户端未提供）");
    }
    println!(
        "  存储       {} @ {:#x}, {} 字节",
        res.pak, res.offset, res.original
    );
    if res.width > 0 {
        println!("  目录尺寸   {}x{}  codec={}", res.width, res.height, res.codec);
    }
    println!("  定位       {how}");
    println!("════════════════════════════════════════════════════════════════");

    // ---------------- 取字节 ----------------
    let Some((pak_name, rec)) = recs.get(&res.hash) else {
        println!("\n✗ 这个 hash 不在任何 .pak 的记录里 —— 无法取字节。");
        println!("  （目录里有记录，但容器索引里没有，说明两者不同源。）");
        std::process::exit(3);
    };
    let pak = &paks[pak_name];
    let dec = match payload::decode(pak, rec) {
        Ok(d) => d,
        Err(e) => {
            println!("\n✗ 取字节失败：{e}");
            std::process::exit(3);
        }
    };
    println!(
        "\n已取出 {} 字节（{}）",
        dec.bytes.len(),
        if dec.info.encrypted { "加密" } else { "明文" }
    );

    // ---------------- 可选：hex dump ----------------
    if a.dump > 0 {
        let n = a.dump.min(dec.bytes.len());
        println!("\n── 前 {n} 字节 ──");
        for row in 0..n.div_ceil(16) {
            let lo = row * 16;
            let hi = (lo + 16).min(n);
            let seg = &dec.bytes[lo..hi];
            let hexs: String = seg.iter().map(|b| format!("{b:02x} ")).collect();
            let asci: String = seg
                .iter()
                .map(|&c| if (0x20..0x7f).contains(&c) { c as char } else { '.' })
                .collect();
            println!("  {:06x}  {:<48} {}", lo, hexs, asci);
        }
    }

    // ---------------- 按类型出视图 ----------------
    let kind = summary::FileKind::route(&res.rtype, &res.ext);
    println!("识别为：{}", kind.label());
    println!();

    match kind {
        summary::FileKind::Texture => {
            let body = summary::texture_summary(&dec.bytes, &res.codec);
            print_view(&body, &con);
            if let Some(dir) = &a.png_out {
                export_png(&dec.bytes, &res, dir);
            }
        }
        summary::FileKind::Material => {
            let body = summary::material_slots(&dec.bytes, |n| resolve_name(&con, n));
            print_view(&body, &con);
        }
        summary::FileKind::Model => {
            let body = summary::mdl_summary(&dec.bytes, |n| resolve_name(&con, n));
            print_view(&body, &con);
        }
        summary::FileKind::Mesh => {
            let body = summary::mesh_summary(&dec.bytes, |n| resolve_name(&con, n));
            print_view(&body, &con);
            // M2-1：几何段（顶点/法线/UV/索引/包围盒）。
            match tlbb_core::preview::parse_geometry(&dec.bytes) {
                Ok(g) => {
                    println!("  几何段     顶点 {} · 三角面 {} · 子网格 {}",
                        g.vertex_count, g.face_count, g.submesh_count);
                    println!(
                        "  包围盒     [{:.2}, {:.2}, {:.2}] ~ [{:.2}, {:.2}, {:.2}]",
                        g.bbox_min[0], g.bbox_min[1], g.bbox_min[2],
                        g.bbox_max[0], g.bbox_max[1], g.bbox_max[2]
                    );
                    let uv_ok = g.uvs.iter().all(|u| u[0].is_finite() && u[1].is_finite());
                    let nrm_bad = g
                        .normals
                        .iter()
                        .filter(|n| n.iter().any(|x| !x.is_finite()))
                        .count();
                    println!(
                        "  数据       索引 {} 个 · UV{} · 法线{} · 中间未解 {} 字节 · 块后剩余 {} 字节",
                        g.indices.len(),
                        if g.uvs.is_empty() {
                            "未解（蒙皮布局）".to_string()
                        } else if uv_ok {
                            "正常".to_string()
                        } else {
                            "含异常值".to_string()
                        },
                        if g.normals.is_empty() {
                            "未解（蒙皮布局）".to_string()
                        } else if nrm_bad == 0 {
                            "正常".to_string()
                        } else {
                            format!("{} 个异常", nrm_bad)
                        },
                        g.middle_bytes,
                        g.trailing_bytes
                    );
                }
                Err(e) => println!("  几何段     ✗ {e}"),
            }
        }
        summary::FileKind::Animation => {
            let body = summary::anim_summary(&dec.bytes);
            print_view(&body, &con);
        }
        summary::FileKind::Skeleton => {
            // .ske 是 JBCF 容器：里面的字符串带角色（骨头名不带扩展名会归 Other，
            // 但骨架引用的 .ani/.mesh 会带）。把非空字符串全部列出，注明来源。
            match jbcf::parse(&dec.bytes) {
                Ok(j) => {
                    println!("骨骼（JBCF 容器，{} 个字符串）", j.strings.len());
                    let mut n = 0;
                    for s in &j.strings {
                        let r = jbcf::role(&s.text);
                        if r == jbcf::Role::Other && s.text.len() < 4 {
                            continue;
                        }
                        println!("  [{:>4}] {}", role_zh(r), s.text);
                        n += 1;
                        if n >= 80 {
                            println!("  …（只显示前 80 条）");
                            break;
                        }
                    }
                    if n == 0 {
                        println!("  （容器里没有可读名字）");
                    }
                }
                Err(e) => println!("✗ 骨骼容器解析失败：{e}"),
            }
        }
        other => {
            // 没有专用预览器：给出字节特征，明确说明"没有更细的视图"。
            let head: Vec<u8> = dec.bytes.iter().copied().take(16).collect();
            println!("（{other:?} 暂无专用预览器）");
            println!("  前 16 字节  {}", hex(&head));
            println!("  头部可打印 {}", printable(&head));
        }
    }
}

fn print_slot(tag: &str, s: &SlotSummary, con: &Connection) {
    match s.resolved {
        Some(h) => {
            let where_at: Option<(String, String)> = con
                .query_row(
                    "select coalesce(type,''), coalesce(path,'') from resources where hash=?1",
                    [format!("{h:016x}")],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .ok();
            let dest = match where_at {
                Some((ty, p)) if !p.is_empty() => format!("{ty} {p}"),
                Some((ty, _)) => format!("{ty}（无名）"),
                None => format!("{h:016x}"),
            };
            println!("  [{tag:>6}] {:<46} → {dest}", s.name);
        }
        None => println!("  [{tag:>6}] {:<46} → 缺", s.name),
    }
}

fn role_zh(r: jbcf::Role) -> &'static str {
    use jbcf::Role::*;
    match r {
        Texture => "贴图",
        Material => "材质",
        Model => "模型",
        Skeleton => "骨骼",
        Animation => "动作",
        Scene => "场景",
        Shader => "着色器",
        Other => "名字",
    }
}

fn print_view(body: &ViewBody, con: &Connection) {
    match body {
        ViewBody::Texture(t) => {
            println!("贴图");
            println!("  尺寸       {} x {}", t.w, t.h);
            println!("  真实编码   {}", t.codec);
            println!("  目录标签   {}", if t.declared_codec.is_empty() { "<无>" } else { &t.declared_codec });
            if !t.declared_codec.is_empty() && !t.declared_codec.eq_ignore_ascii_case(&t.codec) {
                println!("  ⚠ 标签与真实不符（以真实为准）");
            }
            println!("  mip 级数   {}", t.mips);
        }
        ViewBody::Material(slots) => {
            println!("材质槽（{} 个）", slots.len());
            let mut miss = 0;
            for s in slots {
                match s.resolved {
                    Some(h) => {
                        // 显示它到底落在哪 —— 这是预览器最有用的信息
                        let where_at: Option<(String, String)> = con
                            .query_row(
                                "select coalesce(type,''), coalesce(path,'') from resources where hash=?1",
                                [format!("{h:016x}")],
                                |r| Ok((r.get(0)?, r.get(1)?)),
                            )
                            .ok();
                        match where_at {
                            Some((ty, p)) if !p.is_empty() => {
                                println!("  [{:>4}] {:<46} → {} {}", s.role, s.name, ty, p)
                            }
                            Some((ty, _)) => {
                                println!("  [{:>4}] {:<46} → {ty}（无名）", s.role, s.name)
                            }
                            None => println!("  [{:>4}] {:<46} → {:016x}", s.role, s.name, h),
                        }
                    }
                    None => {
                        miss += 1;
                        println!("  [{:>4}] {:<46} → 缺", s.role, s.name);
                    }
                }
            }
            if miss > 0 {
                println!();
                println!("  {miss} 个槽位在资源库里对不上实体（显示为「缺」）。");
                println!("  这是客户端的设计：这些名字存在于材质文件里，但没有对应的路径记录。");
            }
        }
        ViewBody::Unavailable { why } => {
            println!("✗ {why}");
        }
        ViewBody::Raw { bytes, head } => {
            println!("无预览器：{} 字节，头部 {}", bytes, hex(head));
        }
        ViewBody::Model(m) => {
            println!(
                "模型定义  {}（组成清单，全部来自文件内字符串）",
                if m.name.is_empty() { "<无名>" } else { &m.name }
            );
            if !m.base_dir.is_empty() {
                println!("  基目录     {}", m.base_dir);
            }
            for s in &m.skeletons {
                print_slot("骨架", s, con);
            }
            for b in &m.bodies {
                let tag = if b.label.is_empty() {
                    String::new()
                } else {
                    format!("[{}] ", b.label)
                };
                print_slot(&format!("{tag}网格"), &b.mesh, con);
                print_slot(&format!("{tag}材质"), &b.material, con);
            }
            if !m.others.is_empty() {
                println!("  其它成员（挂点/变体名，按文件出现序，语义不断言）");
                for o in m.others.iter().take(30) {
                    println!("    · {o}");
                }
                if m.others.len() > 30 {
                    println!("    …（共 {} 项）", m.others.len());
                }
            }
            let miss = m.skeletons.iter().filter(|s| s.resolved.is_none()).count()
                + m.bodies
                    .iter()
                    .filter(|b| b.mesh.resolved.is_none() || b.material.resolved.is_none())
                    .count();
            if miss > 0 {
                println!();
                println!("  {miss} 项引用在资源库里对不上实体（标「缺」）。");
            }
        }
        ViewBody::Mesh(m) => {
            println!(
                "模型  信封 tag={} v={} 备注={}",
                m.envelope.tag,
                m.envelope.version,
                if m.envelope.note.is_empty() { "<无>".into() } else { m.envelope.note.clone() }
            );
            println!("  版权串     {}", m.envelope.banner);
            if m.refs.is_empty() {
                println!("  （文件里没有内嵌引用名）");
            } else {
                let miss = m.refs.iter().filter(|r| r.resolved.is_none()).count();
                println!("  内嵌引用（{} 个，其中 {} 个对不上实体）", m.refs.len(), miss);
                for s in &m.refs {
                    match s.resolved {
                        Some(h) => {
                            let where_at: Option<(String, String)> = con
                                .query_row(
                                    "select coalesce(type,''), coalesce(path,'') from resources where hash=?1",
                                    [format!("{h:016x}")],
                                    |r| Ok((r.get(0)?, r.get(1)?)),
                                )
                                .ok();
                            match where_at {
                                Some((ty, p)) if !p.is_empty() => {
                                    println!("  [{:>4}] {:<46} → {} {}", s.role, s.name, ty, p)
                                }
                                Some((ty, _)) => {
                                    println!("  [{:>4}] {:<46} → {ty}（无名）", s.role, s.name)
                                }
                                None => println!("  [{:>4}] {:<46} → {:016x}", s.role, s.name, h),
                            }
                        }
                        None => println!("  [{:>4}] {:<46} → 缺", s.role, s.name),
                    }
                }
            }
        }
        ViewBody::Animation(a) => {
            println!(
                "动作  信封 tag={} v={} 备注={}",
                a.envelope.tag,
                a.envelope.version,
                if a.envelope.note.is_empty() { "<无>".into() } else { a.envelope.note.clone() }
            );
            println!("  版权串     {}", a.envelope.banner);
            if a.names.is_empty() {
                println!("  （文件里没有可读名字）");
            } else {
                println!("  文件内可读名（{} 个，多为 Biped 骨架名/备注）", a.names.len());
                for n in a.names.iter().take(40) {
                    println!("    {n}");
                }
                if a.names.len() > 40 {
                    println!("    …（只显示前 40 条）");
                }
            }
        }
    }
}

fn export_png(raw: &[u8], res: &Res, dir: &Path) {
    let Ok(t) = jmt1::decode(raw) else {
        println!("\n✗ 导出 PNG 失败：贴图解不出。");
        return;
    };
    if t.rgba.is_empty() {
        println!("\n✗ 导出 PNG 失败：该编码（{}）没有 RGBA 像素可写。", t.codec.as_str());
        return;
    }
    if std::fs::create_dir_all(dir).is_err() {
        println!("\n✗ 建目录失败：{}", dir.display());
        return;
    }
    let stem = if res.name.is_empty() {
        format!("{:016x}", res.hash)
    } else {
        res.name.rsplit('.').skip(1).collect::<Vec<_>>().join(".")
    };
    let out = dir.join(format!("{stem}.png"));
    match tlbb_core::preview::write_png(&out, t.width, t.height, &t.rgba) {
        Ok(()) => println!("\n✓ 已导出 {}", out.display()),
        Err(e) => println!("\n✗ 写 PNG 失败：{e}"),
    }
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x} ")).collect()
}

fn printable(b: &[u8]) -> String {
    b.iter()
        .map(|&c| if (0x20..0x7f).contains(&c) { c as char } else { '.' })
        .collect()
}
