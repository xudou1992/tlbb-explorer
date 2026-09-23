p = r"D:/TLGL/tlbb-explorer/app/src-tauri/src/data.rs"
s = open(p, encoding="utf-8").read()

s = s.replace("""    pub hub_decoded: bool,
    pub rules: Vec<String>,
    pub hub_asset: Option<Box<Asset>>,
    pub members: Vec<Member>,
}""", """    pub hub_decoded: bool,
    pub rules: Vec<String>,
    pub members: Vec<Member>,
}""")

s = s.replace("""    rules: Vec<String>,
    preview_candidates: Vec<u64>,
    fingerprint: Option<String>,
    hub_asset: Option<Box<Asset>>,
}""", """    rules: Vec<String>,
    preview_candidates: Vec<u64>,
}

impl Row {
    /// A row with nothing in it. The card still lists, and every part of it says 未读到
    /// rather than being filled in with a guess.
    fn empty(group: Group) -> Row {
        Row {
            base: Signals::default(),
            group,
            members: Vec::new(),
            refs: Vec::new(),
            parts: Vec::new(),
            tags: Vec::new(),
            rules: Vec::new(),
            preview_candidates: Vec::new(),
        }
    }
}""")
open(p, "w", encoding="utf-8", newline="\n").write(s)
print("ok")
