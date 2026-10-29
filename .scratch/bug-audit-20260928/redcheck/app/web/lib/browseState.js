// 浏览视图的纯逻辑：把 pak 条目列表整理成文件夹树。不碰 DOM、不发 IPC，
// node --test 直接喂假数据——界面只做渲染。
//
// 纪律：树里只摆客户端原文路径；无名文件全进虚拟目录「(未命名)」，文件名就是
// 16 位编号（顶多补一个已知的扩展名）——编号是身份不是路径，不编造。

// 一条条目（与 Rust browse_tree 回包字段一致）：
//   { hash, path: 有名字符串 | 无名 null, kind, ext, size }
// 树节点：{ name, path, dirs: Map, files: [], depth }

const NAMELESS = "(未命名)";

/// 无名条目的类型词。这批文件在客户端打包时就被剥离了文件名（引擎运行时按
/// 编号寻址，根本不需要名字），但内容分类器判定过的类型是事实，照实摆出来——
/// 分桶展示不算编名字。
const KIND_ZH = {
  texture: "贴图",
  mesh: "网格",
  geom: "未知数据块",
  ani: "动画",
  model: "模型",
  material: "材质",
  scene: "地图格子",
  mapref: "地图引用",
  binary: "二进制",
  tiny: "小文件",
  text: "文本",
  xml: "XML",
  jbcf: "容器数据",
  webp: "WebP 图",
  jpeg: "JPEG 图",
  png: "PNG 图",
};

export function kindZh(kind) {
  if (!kind) return "其他";
  return KIND_ZH[kind.toLowerCase()] || "杂项";
}

export function namelessLabel() {
  return NAMELESS;
}

/// 文件在树行的显示名：有名取路径最后一段；无名用编号（+已知扩展名）。
export function fileNameOf(entry) {
  if (entry.path) {
    const segs = entry.path.split("/").filter(Boolean);
    return segs[segs.length - 1] || entry.hash;
  }
  const ext = (entry.ext || "").replace(/^\./, "");
  return ext ? `${entry.hash}.${ext}` : entry.hash;
}

export function buildTree(entries) {
  const root = { name: "", path: "", dirs: new Map(), files: [], depth: 0 };
  for (const e of entries) {
    if (e.path) {
      const segs = e.path.split("/").filter(Boolean);
      let node = root;
      for (let i = 0; i < segs.length - 1; i++) {
        const nm = segs[i];
        let child = node.dirs.get(nm);
        if (!child) {
          child = {
            name: nm,
            path: node.path ? `${node.path}/${nm}` : nm,
            dirs: new Map(),
            files: [],
            depth: node.depth + 1,
          };
          node.dirs.set(nm, child);
        }
        node = child;
      }
      node.files.push({ ...e, name: segs[segs.length - 1] || e.hash });
    } else {
      // 无名条目按判定的类型分桶：「(未命名)/贴图」「(未命名)/未知数据块」…
      // 文件名仍是编号——分桶是分类事实，不是给它们安名字。
      const bucketName = `${NAMELESS} · ${kindZh(e.kind)}`;
      let bucket = root.dirs.get(bucketName);
      if (!bucket) {
        bucket = {
          name: bucketName,
          path: bucketName,
          dirs: new Map(),
          files: [],
          depth: 1,
          nameless: true,
        };
        root.dirs.set(bucketName, bucket);
      }
      bucket.files.push({ ...e, name: fileNameOf(e) });
    }
  }
  return root;
}

/// 一层的展示行：目录在前、文件在后，本地化排序。limit 截断防卡——
/// 一个图标目录可能上万文件，一次性渲染谁也受不了。
export function childrenOf(node, limit = 400) {
  const dirs = [...node.dirs.values()].sort((a, b) =>
    a.name.localeCompare(b.name, "zh-Hans-CN"),
  );
  const files = [...node.files].sort((a, b) =>
    a.name.localeCompare(b.name, "zh-Hans-CN"),
  );
  const all = [
    ...dirs.map((d) => ({ type: "dir", node: d })),
    ...files.map((f) => ({ type: "file", node: f })),
  ];
  return { rows: all.slice(0, limit), hidden: Math.max(0, all.length - limit) };
}

/// 按关键字过滤：命中路径（无名命中编号）的平铺列表。没给关键字返回 null，
/// 表示「不在搜索态」。
export function searchTree(root, needle, limit = 200) {
  const n = (needle || "").trim().toLowerCase();
  if (!n) return null;
  const out = [];
  const walk = (node) => {
    for (const f of node.files) {
      if ((f.path || f.hash).toLowerCase().includes(n)) {
        out.push(f);
        if (out.length >= limit) return;
      }
    }
    for (const d of node.dirs.values()) {
      walk(d);
      if (out.length >= limit) return;
    }
  };
  walk(root);
  return out;
}

/// 某目录子树里全部文件编号（导出当前文件夹用）。
export function collectHashes(node) {
  const out = [];
  const walk = (n) => {
    for (const f of n.files) out.push(f.hash);
    for (const d of n.dirs.values()) walk(d);
  };
  walk(node);
  return out;
}

/// 导出目标的三态裁决：选中文件=单文件；选中文件夹=整个子树；都没选=整包。
/// 按钮文案和真正的导出必须吃同一份结论——两处各算各的，迟早出现
/// 「按钮说的是 A、导出去的是 B」。返回 null 表示树还没打开，没有可导的目标。
export function exportTargetOf(selectedFile, selectedDir, tree) {
  if (!tree) return null;
  if (selectedFile) {
    return { kind: "file", hashes: [selectedFile.hash], files: 1 };
  }
  if (selectedDir && selectedDir !== tree) {
    return {
      kind: "dir",
      hashes: collectHashes(selectedDir),
      files: countTree(selectedDir).files,
    };
  }
  return { kind: "pak", hashes: [], files: countTree(tree).files };
}

/// 子树统计：文件总数、目录总数（含自身下的所有层级）。
export function countTree(node) {
  let files = node.files.length;
  let dirs = node.dirs.size;
  for (const d of node.dirs.values()) {
    const c = countTree(d);
    files += c.files;
    dirs += c.dirs;
  }
  return { files, dirs };
}

/// 字节数的人话显示。
export function fmtSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}
