const { chromium } = require("playwright-core");
const path = require("path");

(async () => {
  const arg = process.argv[2];
  const file = arg.startsWith("http") ? arg : "file:///" + path.resolve(arg).replace(/\\/g, "/");
  const out = process.argv[3];
  const browser = await chromium.launch({ executablePath: "C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1217/chrome-win64/chrome.exe" });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 });
  const errs = [];
  page.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });
  page.on("pageerror", (e) => errs.push("PAGEERROR: " + e.message));
  await page.goto(file, { waitUntil: "networkidle" });
  // 进资产视图并选中第一条
  await page.evaluate(() => { try { document.getElementById("tabAssets").click(); } catch (e) {} });
  await page.waitForTimeout(700);
  await page.evaluate(() => {
    const r = document.querySelector(".row-item");
    if (r) r.click();
  });
  await page.waitForTimeout(1100);
  await page.screenshot({ path: out });
  console.log("ERRORS:" + JSON.stringify(errs.slice(0, 12), null, 1));
  await browser.close();
})();
