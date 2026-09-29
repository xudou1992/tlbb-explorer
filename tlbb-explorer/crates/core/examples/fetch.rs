//! 研究用取字节工具：按名字从 pak 里取一个资源的原始字节落盘。
//!
//! 逆向时最费时间的不是算，是「把这一条字节拿到手」。命令行示例：
//! ```text
//! cargo run --offline --example fetch -- w1351_monster_xiyuqiezei_walk.ani
//! cargo run --offline --example fetch -- --pak data3 --hash 6c772610af35e0d2 --out /tmp/x.mesh
//! ```
//! 只读：db 只读、pak 只读，只往 --out 写那一个文件。

use std::path::PathBuf;
use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;

fn main() {
    let root = std::env::var("TLBB_ROOT").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let db = std::env::var("TLBB_DB").map(PathBuf::from).unwrap_or_else(|_| root.join(".scratch/resources.db"));
    let mut name = String::new();
    let mut pak_filter = String::new();
    let mut hash = String::new();
    let mut out = PathBuf::new();
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--pak" => pak_filter = args.next().unwrap_or_default(),
            "--hash" => hash = args.next().unwrap_or_default(),
            "--out" => out = PathBuf::from(args.next().unwrap_or_default()),
            other => name = other.to_string(),
        }
    }
    if name.is_empty() && hash.is_empty() {
        eprintln!("用法：fetch [--pak data2] [--hash 16位十六进制] [名字] [--out 路径]");
        std::process::exit(2);
    }

    let con = Connection::open_with_flags(&db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)
        .expect("资源清单打不开");
    // 同名条目按 hash 定位（path 可能为空——无名那批本来就没路径）。
    let (hex, pak): (String, String) = if !hash.is_empty() {
        (hash.clone(), {
            let mut s = con
                .query_row(
                    "SELECT coalesce(pak,'') FROM resources WHERE hash = ?1 LIMIT 1",
                    [hash.as_str()],
                    |r| r.get::<_, String>(0),
                )
                .unwrap_or_default();
            if s.is_empty() {
                s = pak_filter.clone();
            }
            s
        })
    } else {
        let sql = format!(
            "SELECT hash, coalesce(pak,'') FROM resources \
             WHERE path LIKE '%{}{}' {} LIMIT 1",
            "%",
            name.replace('\'', "''"),
            if pak_filter.is_empty() {
                String::new()
            } else {
                format!("AND pak = '{}'", pak_filter.replace('\'', "''"))
            }
        );
        con.query_row(&sql, [], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
            .unwrap_or_else(|e| panic!("清单里找不到 {name}：{e}"))
    };
    if pak.is_empty() {
        panic!("{hex} 在清单里没有所在容器，取不到字节");
    }
    let value: u64 = u64::from_str_radix(hex.trim_start_matches("0x"), 16).expect("编号应是十六进制");

    let pak_file = root.join(format!("{pak}.pak"));
    let container = Pak::open(&pak_file).unwrap_or_else(|e| panic!("打开 {} 失败：{e}", pak_file.display()));
    let rec = container
        .records()
        .find(|r| r.hash == value && r.stored > 0)
        .unwrap_or_else(|| panic!("{pak} 的索引里找不到 {hex}"));
    let bytes = payload::decode(&container, &rec).expect("解字节失败").bytes;

    let dest = if out.as_os_str().is_empty() {
        std::env::temp_dir().join(name.rsplit(['/', '\\']).next().unwrap_or(&format!("{hex}.bin")))
    } else {
        out
    };
    if let Some(dir) = dest.parent() {
        std::fs::create_dir_all(dir).ok();
    }
    std::fs::write(&dest, &bytes).expect("写盘失败");
    println!(
        "{hex} · {pak} · offset={} stored={} original={} → {} bytes={}",
        rec.offset,
        rec.stored,
        rec.original,
        dest.display(),
        bytes.len()
    );
}
