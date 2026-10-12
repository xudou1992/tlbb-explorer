#!/usr/bin/env bash
# 重新生成基线：bash tools/baseline.sh > BASELINE-SHA256.txt
# 用途：任何会话开工前跑一次并对比，diff 出来的就是「谁动了冻结面」。
set -euo pipefail

# --check：拿现值与 BASELINE-SHA256.txt 比对，只报告、不改冻结语义。
#   bash tools/baseline.sh --check            # 有漂移就打印并退 0（咨询用）
#   bash tools/baseline.sh --check --strict   # 冻结面有漂移就退 1（要进 CI 就用这个）
#   BASELINE=某文件 可指向别的基线文件（正反对照用）
if [ "${1:-}" = "--check" ]; then
  BASE="${BASELINE:-BASELINE-SHA256.txt}"
  strict=0
  [ "${2:-}" = "--strict" ] && strict=1
  drift=0; moving_drift=0; gone=0; ok=0; section="FROZEN"
  while IFS= read -r line; do
    case "$line" in
      \#*MOVING*) section="MOVING"; continue ;;
      \#*|"") continue ;;
    esac
    want="${line%% *}"; f="${line#* }"; f="${f#\*}"
    [ -f "$f" ] || { echo "缺失  $f"; gone=$((gone+1)); continue; }
    got="$(sha256sum "$f" | cut -d' ' -f1)"
    if [ "$got" = "$want" ]; then
      ok=$((ok+1))
    elif [ "$section" = "MOVING" ]; then
      echo "漂移(在改) $f"; moving_drift=$((moving_drift+1))
    else
      echo "漂移        $f"; drift=$((drift+1))
    fi
  done < "$BASE"
  echo "对照 $BASE：未变 $ok · 冻结面漂移 $drift · 在改区漂移 $moving_drift · 缺失 $gone"
  if [ "$strict" = 1 ] && [ "$drift" -gt 0 ]; then exit 1; fi
  exit 0
fi
cd "$(dirname "$0")/.."

# v0.1 / v0.2 的冻结面：模型解析、GLB 导出、网页查看器、工作台前端纯函数层。
FROZEN=(
  tlbb-explorer/crates/core/src/preview/geometry.rs
  tlbb-explorer/crates/core/src/export/gltf.rs
  tlbb-explorer/crates/core/src/export/mod.rs
  tlbb-explorer/app/src-tauri/src/mesh_view.rs
  tlbb-explorer/app/web/lib/detailState.js
  tlbb-explorer/app/web/lib/seq.js
  tlbb-explorer/app/web/lib/meshLayout.js
  tlbb-explorer/app/web/lib/wording.js
  tlbb-explorer/app/web/detail.js
  tlbb-explorer/app/web/mesh.js
  tlbb-explorer/app/web/mesh-viewer.js
  tlbb-explorer/app/tests/detailState.test.js
  tlbb-explorer/app/tests/seq.test.js
  tlbb-explorer/app/tests/meshLayout.test.js
  tlbb-explorer/app/tests/wording.test.js
  web-viewer/index.html
  web-viewer/js/app.js
  web-viewer/js/viewer.js
  web-viewer/js/data.js
  web-viewer/js/thumbs.js
  web-viewer/MILESTONE-v0.1-mesh-browser.md
)

# 另一个会话仍在改的文件：只记漂移，不当基线。
MOVING=(
  tlbb-explorer/crates/core/src/preview/scene.rs
)

echo "# BASELINE-SHA256 · v0.1-mesh-browser / v0.2-model-stable 冻结面"
echo "# 生成：bash tools/baseline.sh > BASELINE-SHA256.txt"
echo "# 时间：$(date '+%Y-%m-%d %H:%M')"
echo "# 修订 v0.2.1（2026-09-24）：mesh-viewer.js 经批准改动一次——实例矩阵全链路"
echo "#   不再双转置（527d0b00 → 61f87da7）。改动前的哈希在 git 里，对比用"
echo "#   git diff BASELINE-SHA256.txt；本文件正文由脚本生成，不要手改。"
echo
sha256sum "${FROZEN[@]}"
echo
echo "# ---- MOVING（另一会话在改，只记漂移不作基线）----"
sha256sum "${MOVING[@]}"
