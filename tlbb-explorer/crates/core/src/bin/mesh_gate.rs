//! 全库网格回归闸门：把一棵解包目录里的每个 `.mesh` 过一遍 Rust 解析器，
//! 落 TSV 供 `.scratch/agent_glb_crosscheck.py` 与 Python 参考实现逐行对账。
//!
//! 用法：`mesh_gate <tree目录> <out.tsv>`
use std::io::Write;
use std::path::Path;

use tlbb_core::preview::parse_mesh;

fn walk(dir: &Path, out: &mut Vec<std::path::PathBuf>) {
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

fn main() {
    let mut args = std::env::args().skip(1);
    let root = std::path::PathBuf::from(args.next().expect("缺少解包目录参数"));
    let out_path = args.next().expect("缺少输出 TSV 参数");

    let mut files = Vec::new();
    walk(&root, &mut files);
    files.sort();

    let mut w = std::io::BufWriter::new(std::fs::File::create(&out_path).expect("建不了输出文件"));
    let (mut ok, mut bad) = (0usize, 0usize);
    let (mut with_n, mut with_uv, mut with_ft, mut split_sum) = (0usize, 0usize, 0usize, 0usize);
    let mut leftovers = 0usize;

    for f in &files {
        let raw = match std::fs::read(f) {
            Ok(r) => r,
            Err(e) => {
                bad += 1;
                let _ = writeln!(w, "{}\tREAD_ERR\t{}", f.display(), e);
                continue;
            }
        };
        match parse_mesh(&raw) {
            Ok(l) => {
                ok += 1;
                let g = &l.geometry;
                if !g.normals.is_empty() {
                    with_n += 1;
                }
                if l.uv_sets > 0 {
                    with_uv += 1;
                }
                if l.has_face_table {
                    with_ft += 1;
                }
                if l.face_counts.iter().sum::<u32>() == g.face_count {
                    split_sum += 1;
                }
                if l.middle_leftover > 0 {
                    leftovers += 1;
                }
                let rel = f.strip_prefix(&root).unwrap_or(f.as_path());
                let _ = writeln!(
                    w,
                    "{}\tOK\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
                    rel.display(),
                    raw.len(),
                    g.vertex_count,
                    g.face_count,
                    g.submesh_count,
                    g.middle_bytes,
                    g.trailing_bytes,
                    l.uv_sets,
                    l.has_face_table as u8,
                    l.middle_leftover,
                    g.normals.len(),
                    l.face_counts
                        .iter()
                        .map(|c| c.to_string())
                        .collect::<Vec<_>>()
                        .join("+"),
                );
            }
            Err(e) => {
                bad += 1;
                let rel = f.strip_prefix(&root).unwrap_or(f.as_path());
                let _ = writeln!(w, "{}\tERR\t{}", rel.display(), e.replace('\t', " "));
            }
        }
    }
    w.flush().unwrap();
    println!(
        "mesh={} ok={} err={} normals={} uvs={} face_table={} split_sum_ok={} with_leftover={}",
        files.len(),
        ok,
        bad,
        with_n,
        with_uv,
        with_ft,
        split_sum,
        leftovers
    );
}
