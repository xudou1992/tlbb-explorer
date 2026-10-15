const fs = require("fs");
const base = ".scratch/out/tree/data/source/npc/model";
const targets = [["chuangjue_h001", 66742], ["mhsn_nvsd01", 78744]];
const ok = (c) =>
  (c >= 0x30 && c <= 0x39) || (c >= 0x41 && c <= 0x5a) || (c >= 0x61 && c <= 0x7a) || c === 0x5f;

for (const [key, stop] of targets) {
  const dirs = fs.readdirSync(base).filter((d) => d.includes(key));
  if (!dirs.length) {
    console.log("解包树里没有 " + key);
    continue;
  }
  const d = dirs[0];
  const f = base + "/" + d + "/" + d + ".mesh";
  if (!fs.existsSync(f)) {
    console.log("没解包：" + f);
    continue;
  }
  const b = fs.readFileSync(f);
  const lo = stop - 160;
  const hi = stop + 240;
  const runs = [];
  let i = lo;
  while (i < hi) {
    if (ok(b[i])) {
      let j = i;
      while (j < hi && ok(b[j])) j++;
      if (j - i >= 3) runs.push("+" + (i - stop) + " " + b.slice(i, j).toString("latin1") + "(" + (j - i) + ")");
      i = j;
    } else i++;
  }
  console.log(
    "\n" + d +
      "  死槽=" + stop +
      "  顶点数=" + b.readUInt32LE(0x8c) +
      "  声明骨数=" + b.readUInt32LE(0x110) +
      "  大小=" + b.length
  );
  console.log("  " + runs.join("   "));
}
