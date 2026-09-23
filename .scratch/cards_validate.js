#!/usr/bin/env node
// Acceptance gate for the asset card layer. Run after asset_cards.exe:
//   node cards_validate.js [path/to/cards]
// It checks the emitted JSON and the viewer HTML, so a UI change cannot silently
// regress the information model.

const fs = require('fs');
const path = require('path');

const DIR = process.argv[2] || 'D:/TLGL/.scratch/cards';
const EXPECT = process.argv[3] ? Number(process.argv[3]) : null;
const SPRITES = ['character', 'beast', 'building', 'effect', 'panel', 'item', 'node'];
const OK_TAGS_ASCII = new Set(['NPC']);

const fail = [];
const check = (cond, msg) => { if (!cond) fail.push(msg); };

const doc = JSON.parse(fs.readFileSync(path.join(DIR, 'cards.json'), 'utf8'));
const html = fs.readFileSync(path.join(DIR, 'cards.html'), 'utf8');
const cards = doc['卡片'] || [];

check(cards.length > 0, 'no cards emitted');
if (EXPECT !== null) check(cards.length === EXPECT, `cardCount ${cards.length} != ${EXPECT}`);

let images = 0, brokenImage = 0, dupChip = 0, untranslated = 0, badGrade = 0;
let missingPlaceholder = 0, inventedSubtitle = 0, badRefStatus = 0, cjkName = 0;

for (const c of cards) {
  const name = c['名称'] || '';
  if (/[一-鿿]/.test(name)) cjkName++;                       // names must stay verbatim ASCII

  const tail = (c['副标题'] || '').split('·').pop().trim();
  if (!tail || !name.includes(tail)) inventedSubtitle++;      // subtitle may only cut the stem

  if (c['预览']) {
    images++;
    const p = path.join(DIR, c['预览']);
    if (!fs.existsSync(p) || fs.statSync(p).size === 0) brokenImage++;
  } else if (!SPRITES.includes(c['占位'])) {
    missingPlaceholder++;                                     // imageless cards need a silhouette
  }

  const chips = [...(c['组成'] || []).map(p => p['类型']), ...(c['标签'] || [])];
  if (new Set(chips).size !== chips.length) dupChip++;
  for (const t of c['标签'] || []) {
    if (!/[一-鿿]/.test(t) && !OK_TAGS_ASCII.has(t)) untranslated++;
  }

  const g = (c['证据'] || {})['定位等级'] || '';
  if (!/^[ABCD] /.test(g)) badGrade++;
  if (!Array.isArray((c['证据'] || {})['缺口'])) badGrade++;
  for (const r of c['引用名称'] || []) {
    if (!['已定位', '仅有名称'].includes(r['状态'])) badRefStatus++;
  }
}

check(brokenImage === 0, `brokenImage ${brokenImage} (preview files missing or empty)`);
check(dupChip === 0, `duplicateChip ${dupChip}`);
check(untranslated === 0, `untranslatedTag ${untranslated}`);
check(badGrade === 0, `missingOrBadEvidence ${badGrade}`);
check(missingPlaceholder === 0, `imageless card without a known silhouette ${missingPlaceholder}`);
check(inventedSubtitle === 0, `subtitle not derived from the stem ${inventedSubtitle}`);
check(cjkName === 0, `displayed name contains CJK ${cjkName} (client ships none)`);
check(badRefStatus === 0, `unexpected reference status ${badRefStatus}`);

for (const s of new Set(cards.map(c => c['占位']))) {
  check(html.includes(`id="i-${s}"`), `viewer has no symbol for placeholder "${s}"`);
}
check(html.includes('__JSON__') === false, 'viewer still holds the JSON placeholder');
check(/const DATA=\{[\s\S]+\};/.test(html.replace(/\s+/g, '')) || html.includes('const DATA='),
  'viewer did not inline the card data');

const gradeDist = doc['定位等级分布'] || {};
const scen = doc['场景分布'] || {};
console.log(`cards=${cards.length} images=${images}/${cards.length} ` +
  `refsLocatable=${doc['引用可定位']}/${doc['引用名称总数']}`);
console.log(`scenarios=${JSON.stringify(scen)}`);
console.log(`grades=${JSON.stringify(gradeDist)}`);
if (fail.length) {
  console.error('FAIL');
  for (const f of fail) console.error('  - ' + f);
  process.exit(1);
}
console.log('OK  all structural checks passed');
