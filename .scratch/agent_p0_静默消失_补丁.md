# P0 补丁 · 立体面板不再静默消失（备好待落）

**为什么不直接改**：这两处文件另一会话正在写（`lib/detailState.js` 17:21、`mesh.js` 17:24，
17:29 还重建了 exe），而这个仓库**没有 git**——同一文件并发写不会报冲突，只会后写的静默盖掉先写的。
所以补丁写在这里，等对方会话收工再落；落地后按 §4 验。

**要修的事实**（实测，来自 `resources.db` 13,080 组）：
`app/web/mesh.js` 遇到没有可画网格的组就 `panel.hidden = true`，一个字都不说。
命中 **11,035 / 13,080 = 84.4%** 的资产组；另有 262 组（面板出现的 1,659 组里 15.8%）
在 `mesh_data` 那步失败也只留一句"暂时画不出来"。用户看到的就是"只剩骨骼那一行"。

---

## 1. `app/web/lib/detailState.js` — 在 `loaded()` 末尾换掉立体那段

原文：

```js
  // 立体预览：只有定位到实体的网格才许诺；多网格时默认画第一个。
  const meshes = (insp.mdl && insp.mdl.bodies ? insp.mdl.bodies : [])
    .filter((b) => b.mesh && b.mesh.hash)
    .map((b) => ({ name: b.mesh.path || b.mesh.name, hash: b.mesh.hash, label: b.mesh.name }));
  s.mesh = {
    visible: meshes.length > 0,
    meshes,
    active: meshes.length ? 0 : -1,
    meta: "",
    tech: "",
    state: "",
  };
```

改为：

```js
  // 立体预览：只有定位到实体的网格才许诺；多网格时默认画第一个。
  const mdl = insp.mdl;
  const bodies = (mdl && mdl.bodies) || [];
  const meshes = bodies
    .filter((b) => b.mesh && b.mesh.hash)
    .map((b) => ({ name: b.mesh.path || b.mesh.name, hash: b.mesh.hash, label: b.mesh.name }));
  s.mesh = {
    visible: true, // 面板常驻：空白最让人以为工具坏了
    hasView: meshes.length > 0,
    meshes,
    active: meshes.length ? 0 : -1,
    why: meshWhy(mdl, bodies, meshes, insp),
    meta: "",
    tech: "",
    state: "",
  };
```

并在文件里加一个纯函数（放在 `previewsOf` 旁边即可）：

```js
/// 画不出来时的说法：先说有什么，再说缺哪一环，最后给一句"为什么不是解析失败"。
/// 措辞守 §1 红线：不出现英文角色名、格式术语、编号。
export function meshWhy(mdl, bodies, meshes, insp) {
  const c = insp.counts || {};
  const rows = [];
  rows.push({
    ok: meshes.length > 0,
    label: "能画的网格",
    detail: meshes.length
      ? `${meshes.length} 个，形状与顶点都在文件里`
      : "0 个",
  });
  if (!mdl) {
    rows.push({
      ok: false,
      label: "模型定义",
      detail: c.mesh
        ? `这一组里有 ${c.mesh} 个网格文件，但没有模型定义把部件拼起来——` +
          `哪块是身子、哪块是武器，客户端没说，所以只能一个一个看`
        : "这一组里没有网格文件，本来就没有形状可画（多是图片、材质、动作这类）",
    });
  } else if (bodies.length && !meshes.length) {
    rows.push({
      ok: false,
      label: "模型定义点名的网格",
      detail: `列了 ${bodies.length} 个部件，但一个都没在客户端里找到对应文件——` +
        "客户端只保存名称，没有路径，这是客户端的设计，不是解析失败",
    });
  } else if (!bodies.length) {
    rows.push({ ok: false, label: "部件清单", detail: "模型定义里没写出部件，只有骨架或材质" });
  }
  const missTex = (c.mtl || 0) > 0 && !(insp.previews && insp.previews.items || []).some((x) => x.ok);
  if (missTex) {
    rows.push({ ok: false, label: "花纹", detail: "材质在，但它指的贴图没对上文件，所以只有形状没有花纹" });
  }
  if (c.ani) {
    rows.push({ ok: false, label: "动作", detail: `另有 ${c.ani} 个动作文件，关键帧格式还没解` });
  }
  return rows;
}
```

## 2. `app/web/mesh.js` — `showMeshes()` 不再整块隐藏

原文：

```js
export function showMeshes(meshState) {
  seq.next(); // 换资产就作废上一批在途请求
  meshes = (meshState && meshState.meshes) || [];
  const panel = el("secMesh");
  if (!meshes.length) {
    panel.hidden = true;
    if (viewer) viewer.stop();
    return;
  }
  panel.hidden = false;
  pick(Math.min(Math.max(meshState.active ?? 0, 0), meshes.length - 1));
}
```

改为：

```js
function paintWhy(rows) {
  // 画布收掉，换成一张状态清单：看得见"有什么 / 缺什么"，不留黑框。
  el("meshCanvas").hidden = true;
  el("meshPick").innerHTML = "";
  el("meshMeta").textContent = "";
  el("meshTech").innerHTML = rows
    .map(
      (r) =>
        `<div class="whyrow ${r.ok ? "ok" : "no"}"><b>${r.ok ? "✔" : "✘"}</b>` +
        `<span class="wl">${esc(r.label)}</span><span class="wd">${esc(r.detail)}</span></div>`,
    )
    .join("");
}

export function showMeshes(meshState) {
  seq.next(); // 换资产就作废上一批在途请求
  meshes = (meshState && meshState.meshes) || [];
  el("secMesh").hidden = !(meshState && meshState.visible);
  if (!meshes.length) {
    if (viewer) viewer.stop();
    status("");
    paintWhy((meshState && meshState.why) || [{ ok: false, label: "立体预览", detail: "这一组没读到可画的网格" }]);
    return;
  }
  el("meshCanvas").hidden = false;
  pick(Math.min(Math.max(meshState.active ?? 0, 0), meshes.length - 1));
}
```

## 3. `app/web/style.css` — 两行样式

```css
.whyrow { display: grid; grid-template-columns: 18px 84px 1fr; gap: 6px; padding: 3px 0; font-size: 12.5px; }
.whyrow b { font-weight: 600; }
.whyrow.ok b { color: #57b06a; }
.whyrow.no b { color: var(--warn, #d59b3a); }
.whyrow .wl { color: var(--fg, #dfe6ec); }
.whyrow .wd { color: var(--dim, #8b9aa8); }
```

`index.html` 不用改（`meshCanvas` / `meshTech` 已经在那儿）；改完要 `node web/build.mjs` + 重建 exe 才看得见。

## 4. 验收（改完再跑，别只看一眼）

- 用 `.scratch/ui_check/serve.mjs` 回放真实回包，选 **gid 2410**（`inspect_2410.json` 就是
  `mdl=null` + 三个引用全缺的典型）：断言 `#secMesh` 可见、`.whyrow` ≥ 2 条、里面**没有**
  英文角色名/编号/格式术语（正则查 `mesh|ske|mdl|mtl|gid|hash`，注意茎名里 `shashou` 之类会假命中）。
- 再挑一组 `mdl` 有但 `mesh.hash` 全缺的：应出现"客户端只保存名称，没有路径"这句标准措辞。
- 最后拿一组能画的（`w1351_monster_xiyuqiezei`）确认画布回来了、`.whyrow` 让位给立体：
  以 `readPixels` 亮像素数为准，不信截图（见项目记忆 UI verification workflow）。
