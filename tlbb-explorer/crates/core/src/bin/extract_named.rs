//! 按 cfg 身份把那批「包里有、清单没名字」的件解包出来（只读 pak，产物只写 `--out`）。
//!
//! 为什么要它：`mesh2glb` 吃的是解包目录里的文件，而普查数出来的 4,780 件（能拼出 **232 个
//! 五样齐全的角色集**，见 `.scratch/可补目录的角色集_20261012.md`）在清单里 `path` 是 NULL，
//! 从来没被解出来过——不是解析漏，是**目录里没有它们**。这个工具用已证准的身份
//! （`path_hash(原始全路径) == 包索引哈希`，4,000/4,000 + 零冲突）把路径还给它们，按原路径落盘。
//!
//! 纪律：只读 `resources.db` 与 pak；不写 DB；解不出/读不到的逐条带原话进 `failures`，不凑数。
//!
//! 用法：
//! ```text
//! extract_named --root=D:\TLGL --sidecar=D:\TLGL\.scratch\cfg_named_sidecar.json ^
//!               --out=D:\TLGL\.scratch\out\sidecar_tree --limit=500 --kinds=mesh,ske,ani
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;

struct Args {
    root: PathBuf,
    db: PathBuf,
    sidecar: PathBuf,
    out: PathBuf,
    limit: usize,
    kinds: Vec<String>,
}

fn parse_args() -> Args {
    let mut a = Args {
        root: PathBuf::from("D:/TLGL"),
        db: PathBuf::from("D:/TLGL/.scratch/resources.db"),
        sidecar: PathBuf::from("D:/TLGL/.scratch/cfg_named_sidecar.json"),
        out: PathBuf::from("D:/TLGL/.scratch/out/sidecar_tree"),
        limit: usize::MAX,
        kinds: vec!["mesh".into(), "ske".into(), "ani".into(), "mtl".into(), "mdl".into()],
    };
    for s in std::env::args().skip(1) {
        if let Some(v) = s.strip_prefix("--root=") {
            a.root = PathBuf::from(v);
        } else if let Some(v) = s.strip_prefix("--db=") {
            a.db = PathBuf::from(v);
        } else if let Some(v) = s.strip_prefix("--sidecar=") {
            a.sidecar = PathBuf::from(v);
        } else if let Some(v) = s.strip_prefix("--out=") {
            a.out = PathBuf::from(v);
        } else if let Some(v) = s.strip_prefix("--limit=") {
            a.limit = v.parse().unwrap_or(usize::MAX);
        } else if let Some(v) = s.strip_prefix("--kinds=") {
            a.kinds = v.split(',').map(|x| x.trim().to_ascii_lowercase()).filter(|x| !x.is_empty()).collect();
        } else {
            eprintln!("不认识的参数：{s}（可用 --root= --db= --sidecar= --out= --limit= --kinds=）");
            std::process::exit(2);
        }
    }
    a
}

/// hash(十六进制) -> 所在容器名。清单只认这个，不去猜。
fn pak_of(con: &Connection) -> HashMap<String, String> {
    let mut m = HashMap::new();
    if let Ok(mut st) = con.prepare("select hash, coalesce(pak,'') from resources") {
        if let Ok(it) = st.query_map([], |r| {
            let h: String = r.get(0)?;
            let p: String = r.get(1)?;
            Ok((h, p))
        }) {
            for row in it.flatten() {
                m.insert(row.0.trim().to_ascii_lowercase(), row.1);
            }
        }
    }
    m
}

fn ext_of(path: &str) -> String {
    path.rsplit('.').next().unwrap_or("").to_ascii_lowercase()
}

fn main() {
    let a = parse_args();
    println!("== 按 cfg 身份解包（只读 pak / 只写 --out）");
    println!("  sidecar = {:?}", a.sidecar);
    println!("  out     = {:?}", a.out);

    let raw = std::fs::read(&a.sidecar).expect("读不到 sidecar，先跑 cargo run --bin cfg_named -- --out=…");
    let map: HashMap<String, String> =
        serde_json::from_slice(&raw).expect("sidecar 不是 {hash: path} 的 JSON 对象");
    println!("  sidecar 条目：{}", map.len());

    let con = Connection::open_with_flags(
        &a.db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("只读打开资源清单失败");
    let paks = pak_of(&con);

    let mut cache: HashMap<String, Option<Pak>> = HashMap::new();
    let mut done: HashMap<String, usize> = HashMap::new();
    let mut failures: Vec<(String, String)> = Vec::new();
    let mut written = 0usize;
    let mut tried = 0usize;

    let mut keys: Vec<&String> = map.keys().collect();
    keys.sort();
    for k in keys {
        let path = &map[k];
        let ext = ext_of(path);
        if !a.kinds.iter().any(|x| *x == ext) {
            continue;
        }
        tried += 1;
        if tried > a.limit {
            tried -= 1;
            break;
        }
        let Some(container) = paks.get(&k.to_ascii_lowercase()) else {
            failures.push((path.clone(), "清单里没有这个编号所在的容器".into()));
            continue;
        };
        if container.is_empty() {
            failures.push((path.clone(), "清单说它不在任何 pak 里（可能是散装文件）".into()));
            continue;
        }
        let entry = cache.entry(container.clone()).or_insert_with(|| {
            Pak::open(&a.root.join(format!("{container}.pak"))).ok()
        });
        let Some(pak) = entry else {
            failures.push((path.clone(), format!("容器 {container}.pak 打不开")));
            continue;
        };
        let want = u64::from_str_radix(k.trim().trim_start_matches("0x"), 16).unwrap_or(0);
        let Some(rec) = pak.records().into_iter().find(|r| r.hash == want) else {
            failures.push((path.clone(), "容器里没有这条编号".into()));
            continue;
        };
        match payload::decode(pak, &rec) {
            Ok(dec) => {
                let dest = a.out.join(path.replace('\\', "/").replace('/', std::path::MAIN_SEPARATOR.to_string().as_str()));
                if let Some(dir) = dest.parent() {
                    let _ = std::fs::create_dir_all(dir);
                }
                if let Err(e) = std::fs::write(&dest, &dec.bytes) {
                    failures.push((path.clone(), format!("写不出去：{e}")));
                    continue;
                }
                written += 1;
                *done.entry(ext).or_default() += 1;
            }
            Err(e) => failures.push((path.clone(), format!("解码失败：{e}"))),
        }
    }

    println!("\n落盘：{written} 件（尝试 {} 件）", tried.min(a.limit));
    let mut ks: Vec<_> = done.iter().collect();
    ks.sort_by_key(|(_k, v)| std::cmp::Reverse(**v));
    for (e, n) in ks {
        println!("  .{e:<8} {n:>5}");
    }
    if !failures.is_empty() {
        println!("\n失败的（前 10，共 {} 条）：", failures.len());
        for (p, why) in failures.iter().take(10) {
            println!("  {p}\n      ← {why}");
        }
    }
    let rep = a.out.join("extract_report.json");
    let body = serde_json::to_string_pretty(&serde_json::json!({
        "written": written, "tried": tried, "per_kind": done,
        "failures": failures.iter().take(200).map(|(p, w)| (p, w)).collect::<Vec<_>>(),
    }))
    .unwrap_or_default();
    let _ = std::fs::write(&rep, body);
    println!("\n报告：{}", rep.display());
}
