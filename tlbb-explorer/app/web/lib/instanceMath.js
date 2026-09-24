// 多实例绘制的纯数学。单独抽出来是因为 WebGL 在 node 里开不了，
// 而"矩阵乘在哪一步、包围盒算得对不对、点选反投影成不成"恰恰是最容易错、
// 又最不该靠肉眼在屏幕上验的部分——按项目惯例交给 node --test 钉住。
//
// 两条**贯穿全文件的约定**，读任何一段代码前先记住：
//
//   1) 矩阵一律是 **GL 布局**：`m[c*4+r]` 是第 r 行第 c 列（即 `uniformMatrix4fv`
//      要的列主序存储），点变换写作 `p' = M * p`，展开即
//      `p'.x = m[0]*x + m[4]*y + m[8]*z + m[12]`。
//      于是：三个基向量在 `[0,1,2] [4,5,6] [8,9,10]`，**平移在 `[12,13,14]`**，
//      齐次位在 `[3,7,11]`（恒 0）与 `[15]`（恒 1）。
//      `mul` / `transformPoint` / `rotateY` / `pixelRay` 全部按这一套下标写，
//      没有第二种排布，也**不需要任何转置**。
//
//   2) `.scene` 记录里那 16 个 f32 从 Rust 侧**原样直读**过来，就已经是上面这套
//      下标（客户端存的就是平移在 `[12..14]`）。中间**任何一步再转置都会把平移
//      搬走**：物件会全部叠到原点，而且不报错。这里曾因为注释把这套排布叫作
//      "行主序"，导致 `expandInstances` 多做一次转置 + `pixelRay` 从 `[3,7,11]`
//      取相机，两处同时静默错。所以每个入口都必须点名自己吃的是哪一种排布。
//
//   ⚠ 唯一还没证的：**旋转块要不要转置**。上面那条只钉死平移。旋转部分客户端
//      存的是 `R` 还是 `Rᵀ` 目前没有证据（样本 257 个实例里 0 个旋转块对称，
//      所以这个歧义对每个实例都活着），由 `expandInstances` 的
//      `transposeRotation` 开关承担，默认 `false`（原样直读）。真机比对朝向后
//      一行翻转。**在比对之前，界面不许声称物件朝向正确。**

/// 恒等阵。
export function identity() {
  return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
}

/// 平移阵。GL 布局下平移量落在 m[12..14]。
export function translate(x, y, z) {
  return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]);
}

/// 绕 Y 轴旋转。与 mesh-viewer.js 里 mat4.rotateY 同式，便于两处互相印证。
///
/// 实测这套式子的转向是：rotateY(+90°) 把 +X 送到 **-Z**（不是 +Z）。
/// 绕 X 同理是 rotateX(+90°) 把 +Y 送到 +Z。写测试时别按"教科书右手系"想当然，
/// 以这里实测出来的为准——转向反了不会报错，只会让物件朝错一边。
export function rotateY(rad) {
  const c = Math.cos(rad), s = Math.sin(rad);
  return new Float32Array([c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]);
}

/// M * S 的均匀缩放形式：只缩放前三个基向量，不动平移。
/// GL 布局下三个基向量分别躺在 {m[0],m[1],m[2]}、{m[4],m[5],m[6]}、{m[8],m[9],m[10]}，
/// 所以乘 s 是逐元素散开，不是简单的切片运算。
export function scaleMat(m, s) {
  const o = new Float32Array(m);
  o[0] *= s; o[1] *= s; o[2] *= s;
  o[4] *= s; o[5] *= s; o[6] *= s;
  o[8] *= s; o[9] *= s; o[10] *= s;
  return o;
}

/// a * b（先 b 后 a）。GL 布局：
/// (a*b)[c*4+r] = Σ_k a[k*4+r] * b[c*4+k]，即 a 的第 r 行的第 k 个元素配 b 的第 c 列第 k 个。
export function mul(a, b) {
  const o = new Float32Array(16);
  for (let c = 0; c < 4; c++) {
    for (let r = 0; r < 4; r++) {
      o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
    }
  }
  return o;
}

/// 点变换：p' = M * p（w 取 1，不做透视除法——这些矩阵都是仿射的）。
export function transformPoint(m, p) {
  const x = p[0] ?? 0, y = p[1] ?? 0, z = p[2] ?? 0;
  return [
    m[0] * x + m[4] * y + m[8] * z + m[12],
    m[1] * x + m[5] * y + m[9] * z + m[13],
    m[2] * x + m[6] * y + m[10] * z + m[14],
  ];
}

/// 只转置旋转块（左上 3x3），**平移 `[12..14]` 与齐次位 `[3,7,11,15]` 一个都不动**。
///
/// 这是「客户端存的到底是 `R` 还是 `Rᵀ`」这个未证问题的唯一开关：整阵转置会连平移
/// 一起搬走（那就是全图塌原点的事故），所以这里刻意只做 3x3。转置错了不报错——
/// 表现为物件朝向镜像/反转，位置仍然全对，所以只能靠真机比对定，不能靠看图顺眼。
export function transposeRotationBlock(m) {
  const o = new Float32Array(m);
  const swap = (a, b) => {
    const t = o[a];
    o[a] = o[b];
    o[b] = t;
  };
  swap(1, 4);
  swap(2, 8);
  swap(6, 9);
  return o;
}

/// 从实例矩阵 3x3 部分推法线矩阵（**旋转 + 均匀缩放**假设）。
///
/// 正确做法是 (M^-1)^T，但我们**假设 M 的 3x3 部分不含剪切、且三个轴向缩放相等**
/// （地图摆放里绝大多数就是这个形状：绕某轴转一下 + 整体缩放 + 平移）。
/// 于是 M = R * s，法线该乘的只有 R（旋转不改变垂直关系，均匀缩放整体等比、
/// 归一化后也抵消），直接取 3x3 的三列各自归一化即可——归一化顺带把平移列
/// 之外可能混进来的量级问题按下去，也顺手兜住"某列塌成 0"的退化情形。
///
/// 假设不成立会怎样（诚实交代，不假装普适）：
///   * **非等比缩放**（如 scale(2,1,1)）——法线会歪：本该朝 +X 的面会往 +Y 偏，
///     光照方向错，灰模上表现为明暗分布不对劲。几何位置仍然是对的。
///     要真正做对得给每个实例额外传一个 mat3，代价是每实例多一次 uniformMatrix3fv。
///   * **含剪切**——同理会歪，且比非等比更明显。
///   * 判定：调用方要确认摆放数据只用等比缩放，可用 shapeScaleError() 抽样检查。
///
/// 返回 **GL 布局**的 9 元数组：三个归一化后的基向量依次躺在 `[0..2] [3..5] [6..8]`，
/// 也就是列主序 3x3，可以直接喂 `gl.uniformMatrix3fv`，不用再转一次。
export function normalMatrix3(m) {
  const cols = [
    [m[0], m[1], m[2]],
    [m[4], m[5], m[6]],
    [m[8], m[9], m[10]],
  ];
  const o = new Float32Array(9);
  for (let c = 0; c < 3; c++) {
    const v = cols[c];
    let len = Math.hypot(v[0], v[1], v[2]);
    if (!Number.isFinite(len) || len < 1e-8) {
      // 该轴被压没了：法线无从谈起，退回该轴的单位方向而不是给 NaN。
      len = 1;
      v[0] = c === 0 ? 1 : 0;
      v[1] = c === 1 ? 1 : 0;
      v[2] = c === 2 ? 1 : 0;
    }
    o[c * 3 + 0] = v[0] / len;
    o[c * 3 + 1] = v[1] / len;
    o[c * 3 + 2] = v[2] / len;
  }
  return o;
}

/// 三个轴向缩放长度的相对离散度：(max-min)/max。0 = 等比。
/// 给"要不要相信 normalMatrix3"提供一个可量化的判据，而不是靠感觉。
export function shapeScaleError(m) {
  const len = [
    Math.hypot(m[0], m[1], m[2]),
    Math.hypot(m[4], m[5], m[6]),
    Math.hypot(m[8], m[9], m[10]),
  ];
  if (!len.every((v) => Number.isFinite(v))) return Infinity;
  const mx = Math.max(...len), mn = Math.min(...len);
  if (mx < 1e-8) return Infinity;
  const e = (mx - mn) / mx;
  // 浮点误差会让"本该是 0"的等比缩放出 1e-8 量级。低于这个门槛就归一成 0，
  // 免得调用方要写 `err < 1e-6` 这种自己猜的数字。
  return e < 1e-6 ? 0 : e;
}

/// 实例总表：把 payload.instances 里各自的 16 个 f32 收进一段连续缓冲。
///
/// `.scene` 直读来的排布**已经是 GL 布局**，所以这里默认原样收，不做整阵转置。
/// 唯一可选项是 `opts.transposeRotation`——只翻旋转块，见文件头那条 ⚠。
///
/// 这里刻意不合并成一张大网格：实例只用 4x4 矩阵描述（只能是刚体/相似变换或
/// 不支持的剪切），三个不同网格的三角面各自独立、不可能焊成一份，所以几何
/// 必须按网格分开上传；合并只发生在"矩阵查表"这一层。
export function expandInstances(instances, meshCount, opts) {
  const flipRot = !!(opts && opts.transposeRotation);
  const n = instances.length;
  const out = {
    count: n,
    meshIndex: new Int32Array(n),
    model: new Float32Array(n * 16), // GL 布局，直接喂 uniformMatrix4fv
    normal: new Float32Array(n * 9), // GL 布局 3x3，直接喂 uniformMatrix3fv
  };
  for (let i = 0; i < n; i++) {
    const src = instances[i];
    const mi = Number(src && src.meshIndex);
    // 引用不到的网格不是"画个空的"，是数据错了：宁可这里响，也别静默出一个洞。
    if (!Number.isInteger(mi) || mi < 0 || mi >= meshCount) {
      throw new Error(`第 ${i} 个实例引用了不存在的网格编号 ${src && src.meshIndex}`);
    }
    const raw = src.matrix;
    if (!raw || raw.length !== 16) {
      throw new Error(`第 ${i} 个实例的变换矩阵不是 16 个数（实际 ${raw ? raw.length : 0}）`);
    }
    const row = flipRot ? transposeRotationBlock(Float32Array.from(raw)) : Float32Array.from(raw);
    out.meshIndex[i] = mi;
    out.model.set(row, i * 16);
    // 法线矩阵从最终用的那份矩阵推：开关一旦翻转，光照跟着朝向走，不会两套打架。
    out.normal.set(normalMatrix3(row), i * 9);
  }
  return out;
}

/// 世界包围盒累加器。
///
/// 为什么不能直接用单个网格的 bboxMin/bboxMax 当相机的家：那是**局部**包围盒，
/// 而地图实例带着世界平移。拿局部盒当相机目标，一开图相机就站在某个房子内部，
/// 近裁剪面还会把整片地形切掉。必须逐个实例把局部盒的 8 个角变换到世界再包一次。
export function boundsAccumulator() {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  return {
    /// 把一个**轴对齐**局部盒按实例矩阵变换后并入。变换后未必仍轴对齐，
    /// 所以老老实实按 8 个角求新包围盒——比用半径外扩松一点，但绝不漏。
    ///
    /// 拿不准的输入（没盒子、盒子长度不对、坐标不是有限数）一律**跳过**，
    /// 而不是退化成 0 或 NaN 参与求 min/max：NaN 一进比较就静默不更新，
    /// 结果是整体算出一个看着正常、其实漏了东西的盒子；0 则会把盒子硬拽到原点。
    addBox(m, bboxMin, bboxMax) {
      if (!m || !bboxMin || !bboxMax) return;
      if (bboxMin.length < 3 || bboxMax.length < 3) return;
      if (![...bboxMin.slice(0, 3), ...bboxMax.slice(0, 3)].every((v) => Number.isFinite(v))) return;
      for (let i = 0; i < 8; i++) {
        const p = [
          i & 1 ? bboxMax[0] : bboxMin[0],
          i & 2 ? bboxMax[1] : bboxMin[1],
          i & 4 ? bboxMax[2] : bboxMin[2],
        ];
        const w = transformPoint(m, p);
        if (!w.every((v) => Number.isFinite(v))) continue;
        for (let k = 0; k < 3; k++) {
          if (w[k] < min[k]) min[k] = w[k];
          if (w[k] > max[k]) max[k] = w[k];
        }
      }
    },
    /// 一个实例都没并入时返回 null，让调用方自己决定说什么——不能编一个 {0,0,0} 出来，
    /// 那会让"什么都没读到"看起来像"读到一坨在原点的东西"。
    result() {
      if (!Number.isFinite(min[0])) return null;
      const center = [(min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2];
      // 三个方向都塌成 0（只有单个点）时给一个下限，免得后面 size*0.4 之类的算出 0 距离。
      const size = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2], 1e-3);
      return { min: [...min], max: [...max], center, size };
    },
  };
}

/// 一次算完所有实例的世界包围盒（单网格路径用的是同一套代码，只是实例数 = 1）。
///
/// stride 是给"只抽样一部分实例"留的口子（地图上几万实例时，抽前 500 个
/// 估个大概就够安置相机了）。默认**必须**是 1——写成一个"默认抽样"会让
/// 调用方在完全不知情的情况下拿到一个只包住了头几个实例的盒子，
/// 表现正是"相机卡在某个房子内部"，而且看不出是谁的错。
export function worldBounds(meshes, instances, stride) {
  const step = Math.max(1, Math.floor(stride) || 1);
  const acc = boundsAccumulator();
  for (let i = 0; i < instances.length; i += step) {
    const inst = instances[i];
    const mesh = inst && meshes[inst.meshIndex];
    if (!mesh) continue;
    acc.addBox(inst.matrix, mesh.bboxMin, mesh.bboxMax);
  }
  return acc.result();
}

/// 由屏幕像素坐标算出**世界空间**射线。只依赖相机参数，不碰 WebGL/DOM，所以可测。
///
/// 推导（这套是照着色器里实际的乘法序倒推出来的，不是照教科书抄的）：
/// 相机空间下点 P_cam 经投影得 clip = projection * P_cam，其 x 分量为
///   x_clip = proj[0] * P_cam.x,  w_clip = -P_cam.z
/// 于是 NDC 的 x = x_clip / w_clip = (proj[0] * P_cam.x) / (-P_cam.z)。
/// 取 w_clip = 1（即 P_cam.z = -1）作为这条射线在相机空间的代表点，就有
///   P_cam.x = ndcX / proj[0],  P_cam.y = ndcY / proj[1],  P_cam.z = -1。
/// proj[0] = f/aspect、proj[1] = f（f = 1/tan(fov/2)），代入即得下面的 ax / ay。
///
/// 再回到世界：观察矩阵 view 把世界映射到相机，view = [R | t]。
/// 相机在世界的位置是 -R^T t；而**相机空间的右/上/后**在世界里分别是 R 的
/// 三个行向量，也就是 —— 对列主序的 view 来说 —— view 的第 0、1、2 组四元组
/// [0..2]、[4..6]、[8..10]。因为 R 正交，把相机空间向量 (ax, ay, -1) 搬回世界
/// 只需把这几个世界基向量按分量加权相加：
///   world = ax * right + ay * up + (-1) * back
/// 这里**不出现转置**：R 的行本来就是世界空间里的基，直接用即可。
/// 当初写成 "R^T * dirCam" 就错在这里——那等于把这些基当成系数去配，
/// 方向会整体错位（表现是点左边中右边、或恒不中）。
///
/// view 吃的是 **GL 布局** 16 元矩阵（`mul` / `mat4.*` 出来的就是这套）。GL 布局下平移
/// 在 **12、13、14**，齐次位在 3、7、11 —— 这一条最容易搞反，而且搞反了不报错，
/// 只是相机位置恒等于原点、点选永远从世界原点发出射线。下面按 12..14 取。
export function pixelRay(clientX, clientY, rect, view, fov, aspect) {
  // 像素 → NDC，Y 要翻转：屏幕向下是正，NDC 向上是正。
  const ndcX = ((clientX - rect.left) / Math.max(1, rect.width)) * 2 - 1;
  const ndcY = 1 - ((clientY - rect.top) / Math.max(1, rect.height)) * 2;
  const f = 1 / Math.tan(fov / 2);
  const ax = (ndcX * aspect) / f;
  const ay = ndcY / f;

  // view 把世界映到相机空间，所以它的旋转块 R 是「世界 → 相机」；要回到世界得乘 Rᵀ。
  // GL 布局下 R 的第 r 列就是 flat[r*4 .. r*4+2]，而 Rᵀ 的第 r 行正是它 —— 于是
  // eye = -Rᵀ·t 与 dir = Rᵀ·(ax, ay, -1) 都按**列**取。按行取等于默默乘了 R 本身：
  // 不报错，只是相机位置和视线方向双双转置，点选恒不中。
  const col = (r, k) => view[r * 4 + k];
  const origin = [0, 1, 2].map((r) => -(col(r, 0) * view[12] + col(r, 1) * view[13] + col(r, 2) * view[14]));
  // 方向 = ax · 相机右 + ay · 相机上 + (-1) · 相机后（取负即前）。
  const dir = [0, 1, 2].map((r) => ax * col(r, 0) + ay * col(r, 1) - col(r, 2));
  const len = Math.hypot(dir[0], dir[1], dir[2]) || 1;
  return { origin, dir: [dir[0] / len, dir[1] / len, dir[2] / len] };
}

/// 射线 × 轴对齐包围盒（slab 算法）。返回命中距离 t（取进入面的 t），不命中返回 null。
///
/// 起点已经在盒内时返回 0——那表示"相机就站在这个东西里面"，
/// 对点选来说等于"点中了眼前这个"。（相机被塞进房子里的正确修法是让相机
/// 按**世界**包围盒安置，那是 mesh-viewer.js 的 applyFrame 该管的事，不是这里。）
export function rayBox(origin, dir, mn, mx) {
  let tmin = 0;
  let tmax = Infinity;
  for (let k = 0; k < 3; k++) {
    const d = dir[k];
    if (Math.abs(d) < 1e-9) {
      // 射线平行于这组面：起点不在板层里就永远打不中。
      if (origin[k] < mn[k] || origin[k] > mx[k]) return null;
      continue;
    }
    let t1 = (mn[k] - origin[k]) / d;
    let t2 = (mx[k] - origin[k]) / d;
    if (t1 > t2) [t1, t2] = [t2, t1];
    if (t1 > tmin) tmin = t1;
    if (t2 < tmax) tmax = t2;
    if (tmin > tmax) return null;
  }
  return tmin;
}

/// 挑出被射线打中的实例：改用**世界包围盒**求交，取 t 最小（离相机最近）的那个。
///
/// 这里必须把话说明白：这是**近似**。包围盒是比网格大的一个盒子，所以
///   * 点在物件的空隙里（比如两个树杈之间）也可能判定为命中；
///   * 前面那个盒子挡住后面真实物体的地方，会优先报前面那个。
/// 在"点物件 → 跳 mesh 详情"这个用途上够用——最坏情况是点到旁边的树，
/// 而不是点了个空。要精确得三角形级求交（每帧或每次点击遍历几千个实例的
/// 全部三角面），那是另一个量级的代价，这里不做。
///
/// entries: [{ bound: {min, max}, ... }]，index 即实例下标。返回 {index, t, approximate: true}。
export function nearestHit(origin, dir, entries) {
  let best = null;
  for (let i = 0; i < entries.length; i++) {
    const b = entries[i] && entries[i].bound;
    if (!b) continue;
    const t = rayBox(origin, dir, b.min, b.max);
    if (t === null) continue;
    if (!best || t < best.t) best = { index: i, t, approximate: true };
  }
  return best;
}
