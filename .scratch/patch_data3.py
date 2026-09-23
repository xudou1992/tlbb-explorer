p = r"D:/TLGL/tlbb-explorer/app/src-tauri/src/data.rs"
s = open(p, encoding="utf-8").read()

s = s.replace("pub const DECODERS: usize = 8;", "pub const DECODERS: usize = 10;")

# per-phase wall clocks, summed over shards
s = s.replace("""    blobs: Mutex<HashMap<u64, Option<Arc<Blob>>>>,""",
"""    /// Where the warm-up's wall time went, summed across shards.
    pub t_collect: AtomicUsize,
    pub t_decode: AtomicUsize,
    blobs: Mutex<HashMap<u64, Option<Arc<Blob>>>>,""")
s = s.replace("            blobs: Mutex::new(HashMap::new()),",
              "            t_collect: AtomicUsize::new(0),\n            t_decode: AtomicUsize::new(0),\n            blobs: Mutex::new(HashMap::new()),")
s = s.replace("""                        for chunk in shard.chunks(BATCH) {
                            let rows: Vec<Row> = match &owned {""",
"""                        for chunk in shard.chunks(BATCH) {
                            let tc = Instant::now();
                            let rows: Vec<Row> = match &owned {""")
s = s.replace("""                            let pairs = chunk
                                .iter()
                                .zip(rows)""",
"""                            let td = Instant::now();
                            let pairs = chunk
                                .iter()
                                .zip(rows)""")
s = s.replace("""                                .collect();
                            me.publish(pairs);""",
"""                                .collect();
                            me.t_collect.fetch_add(tc.elapsed().as_micros() as usize, Ordering::Relaxed);
                            me.t_decode.fetch_add(td.elapsed().as_micros() as usize, Ordering::Relaxed);
                            me.publish(pairs);""")
s = s.replace("""            eprintln!("warm: {} 组 / {} 路并行 / {:.1}s", me.total, DECODERS, t0.elapsed().as_secs_f64());""",
"""            eprintln!(
                "warm: {} 组 / {} 路 / 总 {:.1}s（清单 {:.1}s · 主体回读 {:.1}s，均为各分片累计）",
                me.total,
                DECODERS,
                t0.elapsed().as_secs_f64(),
                me.t_collect.load(Ordering::Relaxed) as f64 / 1e6,
                me.t_decode.load(Ordering::Relaxed) as f64 / 1e6
            );""")
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("ok")
