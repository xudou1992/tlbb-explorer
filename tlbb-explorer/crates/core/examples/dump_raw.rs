// 一次性修复本机测试夹具：从 pak 直接落原始字节（不落文本、不做 lossy 转换）。
// 用法（在 crates/core 下）：cargo run --offline --example dump_raw
use std::path::PathBuf;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;

fn main() {
    let mut root = PathBuf::from("D:/TLGL");
    let mut out = PathBuf::from("tests");
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--root" => root = PathBuf::from(args.next().unwrap_or_default()),
            "--out" => out = PathBuf::from(args.next().unwrap_or_default()),
            o => eprintln!("未知参数 {o}"),
        }
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
