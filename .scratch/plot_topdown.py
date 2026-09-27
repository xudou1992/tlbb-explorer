# 顶视图：把一张图的实例 footprint 按两种旋转解释各画一遍，和小地图对形状。
# 跑法：python .scratch/plot_topdown.py [地图ID]
import json, sys
from PIL import Image, ImageDraw

ID = sys.argv[1] if len(sys.argv) > 1 else "w1351_fb_wanjiegu_002"
d = json.load(open(f".scratch/ui_check/map_scene_{ID}.json", encoding="utf-8"))


def world_xz(inst, transpose):
    m = inst["matrix"]
    mx = d["meshes"][inst["meshIndex"]]
    x0, z0 = mx["bboxMin"][0], mx["bboxMin"][2]
    x1, z1 = mx["bboxMax"][0], mx["bboxMax"][2]
    pts = []
    for lx, lz in ((x0, z0), (x1, z0), (x1, z1), (x0, z1)):
        if transpose:
            wx = m[0] * lx + m[1] * lz + m[12]
            wz = m[8] * lx + m[9] * lz + m[14]
        else:
            wx = m[0] * lx + m[8] * lz + m[12]
            wz = m[2] * lx + m[10] * lz + m[14]
        pts.append((wx, wz))
    return pts


def panel(transpose, tag):
    # 客户端数据里真有摆到几万公里外的野物件（实测 wanjiegu_002 有一条大榕树在
    # (-54922, 30, -84617)，格子名还和它对得上）——不剔掉整张图会被压成一个点。
    far = [it for it in d["instances"] if max(abs(it["matrix"][12]), abs(it["matrix"][14])) > 2000]
    keep = [it for it in d["instances"] if max(abs(it["matrix"][12]), abs(it["matrix"][14])) <= 2000]
    polys = [world_xz(it, transpose) for it in keep]
    xs = [p[0] for q in polys for p in q]
    zs = [p[1] for q in polys for p in q]
    minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
    W = H = 820
    pad = 34
    s = min((W - 2 * pad) / max(maxx - minx, 1e-6), (H - 2 * pad) / max(maxz - minz, 1e-6))
    im = Image.new("RGB", (W, H), (14, 18, 22))
    dr = ImageDraw.Draw(im)
    for q in polys:
        pts = [((p[0] - minx) * s + pad, (H - pad) - (p[1] - minz) * s) for p in q]
        dr.polygon(pts, outline=(168, 214, 255), fill=(56, 86, 106))
    dr.text((pad, 10),
            f"{ID}  {'转置解释' if transpose else '直读解释'}   跨度 {maxx-minx:.0f} x {maxz-minz:.0f} 单位   footprint {len(polys)}（剔掉 {len(far)} 条离谱坐标）",
            fill=(255, 232, 150))
    im.save(f".scratch/topdown_{ID}_{tag}.png")
    print(f"{tag}: 跨度 {maxx-minx:.0f} x {maxz-minz:.0f}，{len(polys)} 个 footprint，"
          f"x {minx:.0f}..{maxx:.0f}  z {minz:.0f}..{maxz:.0f}")


panel(False, "direct")
panel(True, "transposed")
