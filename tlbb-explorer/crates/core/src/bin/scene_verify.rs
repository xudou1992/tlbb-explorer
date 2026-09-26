//! 对 `crates/core/tests/scene_samples/` 下三个样本跑一遍 `parse_scene`，
//! 打印完整数值表（含前 3 条的 name / position 与矩阵平移列）。
//!
//! 这是**只读校验**，直接读磁盘上的样本文件——即测试真正会读到的那些字节。
//!
//!   cargo run --bin scene_verify

use std::path::PathBuf;

use tlbb_core::preview::scene::{is_empty_grid, parse_scene};

fn main() {
    let dir = PathBuf::from(
        "D:/TLGL/tlbb-explorer/crates/core/tests/scene_samples",
    );
    let out = PathBuf::from("D:/TLGL/.scratch/scene_verify.txt");
    let mut log: Vec<String> = Vec::new();
    let mut say = |s: String, log: &mut Vec<String>| {
        println!("{s}");
        log.push(s);
    };

    say(format!("sample dir = {}", dir.display()), &mut log);
    for name in [
        "grid_749.scene",
        "grid_753_overstated.scene",
        "grid_753_with_tail.scene",
    ] {
        let path = dir.join(name);
        let raw = match std::fs::read(&path) {
            Ok(r) => r,
            Err(e) => {
                say(format!("\n{name}: READ FAILED {e}"), &mut log);
                continue;
            }
        };
        say(
            format!(
                "\n=== {name} ===\n  abs path   = {}\n  bytes      = {}\n  is_empty_grid = {}",
                path.display(),
                raw.len(),
                is_empty_grid(&raw)
            ),
            &mut log,
        );
        say(
            format!(
                "  header u32 = [n_records={}, tag={}, zero={}]",
                u32::from_le_bytes(raw[0..4].try_into().unwrap()),
                u32::from_le_bytes(raw[4..8].try_into().unwrap()),
                u32::from_le_bytes(raw[8..12].try_into().unwrap()),
            ),
            &mut log,
        );
        match parse_scene(&raw) {
            Err(e) => say(format!("  parse_scene => Err({e:?})"), &mut log),
            Ok(g) => {
                say(
                    format!(
                        "  parse_scene => Ok\n    tag          = {}\n    stride       = {}\n    u32@0 (declared) = {}\n    instances.len()  = {}\n    tail_bytes       = {}\n    has_tail         = {}\n    understated      = {}\n    consumed     = {} + {}*{} = {}\n    len - consumed   = {}",
                        g.tag,
                        g.stride,
                        g.declared,
                        g.instances.len(),
                        g.tail_bytes,
                        g.has_tail,
                        g.understated,
                        12,
                        g.stride,
                        g.instances.len(),
                        12 + g.stride * g.instances.len(),
                        raw.len() as i64 - (12 + g.stride * g.instances.len()) as i64,
                    ),
                    &mut log,
                );
                for (i, inst) in g.instances.iter().take(3).enumerate() {
                    say(
                        format!(
                            "    [{i}] name = {}\n         position = {:?}\n         m[12..15] = {:?}  m[3],m[7],m[11],m[15] = {:?}",
                            inst.name,
                            inst.position,
                            &inst.matrix[12..15],
                            [inst.matrix[3], inst.matrix[7], inst.matrix[11], inst.matrix[15]],
                        ),
                        &mut log,
                    );
                }
                // 判据 M/N 全量自检
                let all_m = g.instances.iter().all(|i| {
                    i.matrix[3] == 0.0
                        && i.matrix[7] == 0.0
                        && i.matrix[11] == 0.0
                        && i.matrix[15] == 1.0
                });
                say(format!("    判据M 全条成立 = {all_m}"), &mut log);
            }
        }
    }

    std::fs::write(&out, log.join("\n")).ok();
    eprintln!("wrote {}", out.display());
}
