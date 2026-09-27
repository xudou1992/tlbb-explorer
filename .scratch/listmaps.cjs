const l = JSON.parse(require("fs").readFileSync(".scratch/ui_check/map_list.json", "utf8"));
const g = {};
for (const r of l) {
  const p = r.id.split("_");
  const k = p[1] || "?";
  const stem = p.slice(2).join("_").replace(/_\d+$/, "");
  (g[k] = g[k] || new Set()).add(stem);
}
for (const k of Object.keys(g)) console.log("[" + k + "] " + g[k].size + " 种: " + [...g[k]].sort().join(" "));
