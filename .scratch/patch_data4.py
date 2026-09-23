p = r"D:/TLGL/tlbb-explorer/app/src-tauri/src/data.rs"
s = open(p, encoding="utf-8").read()

s = s.replace("""/// Threads decoding container payloads; decoding is CPU bound (decrypt + Snappy).
pub const DECODERS: usize = 10;""",
"""/// Shards in the background pass. The catalog queries dominate (see `refs_from`), so the
/// shell spreads them over the machine instead of serialising on one read handle.
pub fn shards() -> usize {
    std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
        .clamp(4, 16)
}""")
s = s.replace("            let per = me.total.div_ceil(DECODERS).max(BATCH);",
              "            let lanes = shards();\n            let per = me.total.div_ceil(lanes).max(BATCH);")
s = s.replace("""                me.total,
                DECODERS,""", """                me.total,
                lanes,""")
s = s.replace("""            eprintln!(
                "warm: {} 组 / {} 路 / 总 {:.1}s（清单 {:.1}s · 主体回读 {:.1}s，均为各分片累计）",""",
"""            eprintln!(
                "warm: {} 组 / {} 路 / 总 {:.1}s（清单查询 {:.1}s · 主体回读 {:.1}s，均为各分片累计）",""")

# search must stay responsive while the background pass runs: top up only when the
# warmed rows cannot fill a page.
s = s.replace("""        if !ql.is_empty() {""", """        if !ql.is_empty() && hits.len() < 40 {""")
s = s.replace("""                    .map(|g| g.id)
                    .take(200)
                    .collect()""","""                    .map(|g| g.id)
                    .take(80)
                    .collect()""")
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("ok")
