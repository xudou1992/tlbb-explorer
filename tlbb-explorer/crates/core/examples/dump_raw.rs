// 从 pak 直接落原始字节（不落文本、不做 lossy 转换）。
// 默认修两份测试夹具；给了 --hash/--pak 就只导那一条，供研究用。
// 用法（在 crates/core 下）：cargo run --offline --example dump_raw [-- --pak data --hash bcd65050a62986b7 --out ../../.scratch/raw]
use std::path::PathBuf;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;

fn main() {
    let mut root = PathBuf::from("D:/TLGL");
    let mut out = PathBuf::from("tests");
    let mut hash: Option<u64> = None;
    let mut pak_name = String::from("data");
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--root" => root = PathBuf::from(args.next().unwrap_or_default()),
            "--out" => out = PathBuf::from(args.next().unwrap_or_default()),
            "--pak" => pak_name = args.next().unwrap_or_default(),
            "--hash" => {
                let h = args.next().unwrap_or_default();
                hash = u64::from_str_radix(h.trim_start_matches("0x"), 16).ok();
                if hash.is_none() {
                    eprintln!("hash 得是 16 进制：{h}");
                    std::process::exit(2);
                }
            }
            o => eprintln!("未知参数 {o}"),
        }
    }
    if let Some(h) = hash {
        let pak = Pak::open(root.join(format!("{pak_name}.pak"))).expect("pak 打开失败");
        let rec = pak
            .records()
            .find(|r| r.hash == h && r.stored > 0)
            .unwrap_or_else(|| panic!("{pak_name} 里找不到 {h:016x}"));
        let bytes = payload::decode(&pak, &rec).expect("解字节失败").bytes;
        std::fs::create_dir_all(&out).ok();
        let file = out.join(format!("{h:016x}.raw"));
        std::fs::write(&file, &bytes).expect("写盘失败");
        println!("{h:016x} ← {pak_name}  bytes={} → {}", bytes.len(), file.display());
        return;
    }
    let jobs = [
        ("w1351_model_emiter_lf002.mesh", "data", 0x401e639268cc7a0cu64),
        ("w1351_model_emiter_lf004.mesh", "data3", 0x6c772610af35e0d2u64),
    ];
    for (name, pak_name, hash) in jobs {
        let pak = Pak::open(root.join(format!("{pak_name}.pak"))).expect("pak 打开失败");
        let rec = pak
            .records()
            .find(|r| r.hash == hash && r.stored > 0)
            .unwrap_or_else(|| panic!("{pak_name} 里找不到 {hash:016x}"));
        let bytes = payload::decode(&pak, &rec).expect("解字节失败").bytes;
        std::fs::write(out.join(name), &bytes).expect("写盘失败");
        println!("{} ← {pak_name}  bytes={}", name, bytes.len());
    }
}
