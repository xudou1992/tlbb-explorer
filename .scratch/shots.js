const { chromium } = require("playwright-core");

const EXE = "C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe";
const URL = "http://127.0.0.1:8791/preview.html";
const OUT = process.argv[2] || "C:/Users/Administrator/AppData/Local/Temp";

(async () => {
  const browser = await chromium.launch({ executablePath: EXE });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 });
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });
  page.on("pageerror", (e) => errs.push("PAGEERROR: " + e.message));
  await page.goto(URL, { waitUntil: "networkidle" });
  await page.evaluate(() => { try { document.getElementById("tabAssets").click(); } catch (e) {} });
  await page.waitForTimeout(700);
  await page.evaluate(() => { const r = document.querySelector(".row-item"); if (r) r.click(); });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: OUT + "/v_preview.png" });

  // 资源详情标签
  await page.evaluate(() => document.querySelector('.tab[data-tab="resource"]').click());
  await page.waitForTimeout(500);
  await page.screenshot({ path: OUT + "/v_resource.png" });

  // 引用关系标签
  await page.evaluate(() => document.querySelector('.tab[data-tab="relations"]').click());
  await page.waitForTimeout(400);
  await page.screenshot({ path: OUT + "/v_relations.png" });

  // 缺失资源标签
  await page.evaluate(() => document.querySelector('.tab[data-tab="missing"]').click());
  await page.waitForTimeout(400);
  await page.screenshot({ path: OUT + "/v_missing.png" });

  // 关系网浮层
  await page.evaluate(() => document.getElementById("openRelations").click());
  await page.waitForTimeout(700);
  await page.screenshot({ path: OUT + "/v_graph.png" });
  await page.evaluate(() => document.getElementById("closeRelations").click());
  await page.waitForTimeout(300);

  // 报告浮层
  await page.evaluate(() => document.getElementById("openHealth").click());
  await page.waitForTimeout(800);
  await page.screenshot({ path: OUT + "/v_health.png" });
  await page.evaluate(() => document.getElementById("closeHealth").click());

  // 浏览第一屏
  await page.evaluate(() => document.getElementById("tabBrowse").click());
  await page.waitForTimeout(700);
  await page.screenshot({ path: OUT + "/v_browse.png" });

  console.log("ERRORS:" + JSON.stringify([...new Set(errs)].slice(0, 10), null, 1));
  await browser.close();
})();
