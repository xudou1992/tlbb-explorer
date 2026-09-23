import re
p = r"D:/TLGL/tlbb-explorer/app/src-tauri/src/data.rs"
s = open(p, encoding="utf-8").read()

# 1. drop the obsolete batch decoder (superseded by the shard-parallel warm pass)
a = s.index("    fn decode_and_publish(&self, rows: Vec<Row>) {")
b = s.index("        self.scanned.store(order.len(), Ordering::SeqCst);\n    }\n")
s = s[:a] + s[b + len("        self.scanned.store(order.len(), Ordering::SeqCst);\n    }\n"):]

# 2. textures_in_dir now runs against the shard's own handle
s = s.replace("""            preview_candidates.extend(
                self.q(|c| c.textures_in_dir(&g.dir))
                    .into_iter()
                    .map(|(h, _)| h),
            );""",
"""            preview_candidates
                .extend(one(cat.textures_in_dir(&g.dir)).into_iter().map(|(h, _)| h));""")

# 3. the shared-handle query helper is only used by `asset`/`extras` now: keep `q`,
#    add the free `one` used on a borrowed handle
s = s.replace("""fn hex(h: u64) -> String {""",
"""/// A catalog query that must not take a card down with it: a group whose rows cannot be
/// read is still listed, it simply says so.
fn one<T: Default>(r: tlbb_core::catalog::sqlite::Result<T>) -> T {
    match r {
        Ok(v) => v,
        Err(e) => {
            eprintln!("清单查询失败：{e}");
            T::default()
        }
    }
}

fn hex(h: u64) -> String {""")

# 4. Row::empty for the fallback path
s = s.replace("""/// What one warm-up batch learned from the catalog, before the decode pass.
struct Row {""",
"""/// What one warm-up batch learned from the catalog, before the decode pass.
struct Row {""")
s = s.replace("""    fn collect_locked(&self, g: &Group) -> Row {""",
"""    fn collect_locked(&self, g: &Group) -> Row {""")
s = s.replace("""            preview_candidates,
        }
    }""","""            preview_candidates,
        }
    }

    /// A row with nothing in it: the card still shows, and every field says 未读到.
    fn empty(group: Group) -> Row {
        Row {
            group,
            base: Signals::default(),
            members: Vec::new(),
            refs: Vec::new(),
            parts: Vec::new(),
            tags: Vec::new(),
            rules: Vec::new(),
            preview_candidates: Vec::new(),
        }
    }""")

# 5. retire the discovery-order list and the phase counters
s = s.replace("""    /// Discovery order of the warmed rows, so the grid stays stable while filling in.
    order: Mutex<Vec<i64>>,
""", "")
s = s.replace("            order: Mutex::new(Vec::new()),\n", "")
s = s.replace("""    /// Diagnostics for the warm-up: where the wall time actually goes.
    pub t_collect: AtomicUsize,
    pub t_decode: AtomicUsize,
""", "")
s = s.replace("            t_collect: AtomicUsize::new(0),\n            t_decode: AtomicUsize::new(0),\n", "")

# 6. page(): iterate the warmed map, and top up missing search hits on demand
s = s.replace("""        let order = self.order.lock().map(|o| o.clone()).unwrap_or_default();
        let mut hits: Vec<Arc<Lite>> = match self.lite.lock() {
            Ok(lite) => order
                .iter()
                .filter_map(|gid| lite.get(gid))
                .filter(|l| self.keeps(l, f, &keys, &ql))
                .cloned()
                .collect(),
            Err(_) => Vec::new(),
        };""",
"""        let mut hits: Vec<Arc<Lite>> = match self.lite.lock() {
            Ok(lite) => lite
                .values()
                .filter(|l| self.keeps(l, f, &keys, &ql))
                .cloned()
                .collect(),
            Err(_) => Vec::new(),
        };
        // A search must work in the first second, not only after the warm-up: names that
        // still have no row are read right now (name and folder only, so no guessing).
        if !ql.is_empty() {
            let missing: Vec<i64> = {
                let lite = match self.lite.lock() {
                    Ok(l) => l,
                    Err(_) => return Page::default(),
                };
                self.groups
                    .iter()
                    .filter(|g| {
                        !lite.contains_key(&g.id)
                            && search::matches_asset(&g.stem, &g.dir, &keys)
                    })
                    .map(|g| g.id)
                    .take(200)
                    .collect()
            };
            if !missing.is_empty() {
                self.ensure(&missing);
                if let Ok(lite) = self.lite.lock() {
                    for gid in missing {
                        if let Some(l) = lite.get(&gid) {
                            if self.keeps(l, f, &keys, &ql) && !hits.iter().any(|h| h.group.id == l.group.id) {
                                hits.push(Arc::clone(l));
                            }
                        }
                    }
                }
            }
        }""")

# 7. Page needs a default for that bail-out path
p2 = r"D:/TLGL/tlbb-explorer/app/src-tauri/src/model.rs"
m = open(p2, encoding="utf-8").read()
m = m.replace("""#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Page {""", """#[derive(Serialize, Default, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Page {""")
open(p2, "w", encoding="utf-8", newline="\n").write(m)

open(p, "w", encoding="utf-8", newline="\n").write(s)
print("patched")
