// The frontend is dependency-free on purpose: plain ES modules and CSS, copied
// verbatim into web/dist for Tauri to embed. No bundler, so the build works offline.
import { cpSync, rmSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = dirname(fileURLToPath(import.meta.url));
const dist = join(web, "dist");

rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });
for (const entry of readdirSync(web)) {
  if (entry === "dist" || entry === "build.mjs") continue;
  cpSync(join(web, entry), join(dist, entry), { recursive: true });
}
console.log(`web -> ${dist}`);
