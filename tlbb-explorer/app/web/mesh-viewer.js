// M2-2 · 灰模预览：原生 WebGL 1.0，无第三方依赖。
//
// 数据来自 mesh_data：一段 base64 小端缓冲
//   位置 vc×3×f32 → 法线 vc×3×f32（有则给）→ UV vc×2×f32 → 索引 ic×u16
// 字节布局与校验在 lib/meshLayout.js（有 node --test 盯着），这里只管画。
// 没解出法线的模型（蒙皮类，中间段未读）由这里按面自算法线——
// 那是几何推导，不是猜数据，所以照实画；背面不剔除，因为这个格式的绕序还没核实。
//
// M2-9 · 同一份代码还要画**多实例**（一个网格文件按 N 个 4x4 变换摆 N 次，
// 比如同一棵树在城里摆 300 份）。两条路径共用一个 program、一套几何池，
// 靠 uUseInst 一个 uniform 分流，单网格那一路的取值和以前逐位一致。
// 矩阵约定、包围盒、点选反投影这些纯数学在 lib/instanceMath.js 里，有 node --test。

import { validateMesh } from "./lib/meshLayout.js";
import { boneLineVertices } from "./lib/boneLines.js";
import * as im from "./lib/instanceMath.js";

const VS = `
attribute vec3 aPosition;
attribute vec3 aNormal;
uniform mat4 uModelView;
uniform mat4 uProjection;
// uInstance：实例的模型矩阵（**GL 布局**，scene 记录直读过来就是这个排布，不转置）。
// uNormalMat：实例法线矩阵（**GL 布局** 3x3，由 expandInstances 按"旋转+均匀缩放"
//             假设算好，同样直接喂 uniformMatrix3fv）。
// uUseInst：0 = 单网格老路径，1 = 多实例路径。用 uniform 分流而不是写两个 program，
// 是为了让"老路径没被顺手改坏"这件事只取决于一个数字，肉眼可核。
uniform mat4 uInstance;
uniform mat3 uNormalMat;
uniform float uUseInst;
varying vec3 vNormal;
varying vec2 vUv;
attribute vec2 aUv;
varying vec3 vView;
void main() {
  // 实例矩阵**乘在 uModelView 之后**，即 uModelView * instance * pos：
  //   * uModelView 已经含相机与"把模型挪到原点"的居中平移，是**场景级**的东西；
  //   * 实例矩阵描述的是"这个物件在场景里摆哪儿"，是**物件级**的东西。
  //     物件级变换先作用于局部坐标、再交给场景级变换，编译成矩阵就是这一个乘法序。
  //   * 反过来的 instance * uModelView * pos 在数学上也自洽，但那样实例矩阵会
  //     被相机的居中平移一起带偏（物件的落点会跟着相机目标跑），摆出来的地图全歪，
  //     而且每改一次相机就要重算全部实例矩阵。所以不取那一种。
  vec4 local = uUseInst > 0.5 ? uInstance * vec4(aPosition, 1.0) : vec4(aPosition, 1.0);
  vec3 nrm = uUseInst > 0.5 ? uNormalMat * aNormal : aNormal;
  vec4 mv = uModelView * local;
  vView = mv.xyz;
  vNormal = mat3(uModelView) * nrm;
  vUv = aUv;
  gl_Position = uProjection * mv;
}`;

// 双面半兰伯特：绕序未知时剔除会整块黑，故只靠法线朝向翻转补光。
const FS = `
precision mediump float;
varying vec3 vNormal;
varying vec3 vView;
varying vec2 vUv;
uniform sampler2D uTex;
uniform float uUseTex;
uniform sampler2D uMask;
uniform float uUseMask;
// 特效层是发光的叠加片，不参与灰模的漫反射；基础层仍按半兰伯特打光。
uniform float uUnlit;
// 场景光照强度：地图页按客户端 .sfl 的环境光填（默认 1 就是原来的亮度）。
uniform float uLight;
void main() {
  vec3 n = normalize(vNormal);
  vec3 l = normalize(vec3(0.35, 0.75, 0.6));
  float d = dot(n, l) * 0.5 + 0.5;
  float rim = pow(1.0 - abs(dot(normalize(-vView), n)), 2.0) * 0.25;
  vec4 tex = texture2D(uTex, vUv);
  float m = 1.0;
  if (uUseMask > 0.5) {
    vec4 mk = texture2D(uMask, vUv);
    // 客户端 mask 有的用 alpha、有的用灰度；取两者最大，避免整层消失。
    m = max(mk.a, max(mk.r, max(mk.g, mk.b)));
  }
  vec3 base = mix(vec3(0.62, 0.65, 0.69), tex.rgb, uUseTex);
  vec3 lit = base * (0.32 + 0.68 * d) * uLight + rim;
  vec3 col = mix(lit, tex.rgb, uUnlit);
  float a = uUseTex > 0.5 ? (uUseMask > 0.5 ? tex.a * m : tex.a) : 1.0;
  gl_FragColor = vec4(col, a);
}`;

// 骨头连线单独一条程序。灰模那对 VS/FS 的数字不动：没传骨头时这条程序不会被 use。
// 骨在网格体积里面，开着深度测试会被灰模挡住，绑定姿态的线就看不见。
// 只在画线这一下关掉深度，画完立刻恢复。
const BONE_VS = `
attribute vec3 aPosition;
uniform mat4 uModelView;
uniform mat4 uProjection;
uniform float uPointSize;
void main() {
  gl_Position = uProjection * uModelView * vec4(aPosition, 1.0);
  gl_PointSize = uPointSize;
}`;

const BONE_FS = `
precision mediump float;
uniform vec4 uColor;
void main() {
  // 颜色由调用方给：骨线青色（和暖色衣料区分），地图点选框橙色。
  gl_FragColor = uColor;
}`;

// 视场角。抽成常量是因为 draw() 用它投影、pickAt 用它反投影——
// 两处各写一个数字，改了其中一处就会出现"看着点中了，其实偏一条街"。
const FOV = Math.PI / 4.5;

function loadImage(src) {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = () => rej(new Error("贴图解码失败"));
    img.src = src;
  });
}

function uploadTexture(gl, img) {
  const t = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, t);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  return t;
}

function compile(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    throw new Error("着色器编译失败（这是我们代码的 bug，不是你机器的问题）：" + gl.getShaderInfoLog(sh));
  }
  return sh;
}

// 蒙皮类模型没解出法线，按面累加再归一化，得到平滑灰模。
function faceNormals(positions, indices) {
  const n = new Float32Array(positions.length);
  for (let i = 0; i < indices.length; i += 3) {
    const a = indices[i] * 3, b = indices[i + 1] * 3, c = indices[i + 2] * 3;
    const e1x = positions[b] - positions[a], e1y = positions[b + 1] - positions[a + 1], e1z = positions[b + 2] - positions[a + 2];
    const e2x = positions[c] - positions[a], e2y = positions[c + 1] - positions[a + 1], e2z = positions[c + 2] - positions[a + 2];
    const nx = e1y * e2z - e1z * e2y, ny = e1z * e2x - e1x * e2z, nz = e1x * e2y - e1y * e2x;
    for (const v of [a, b, c]) { n[v] += nx; n[v + 1] += ny; n[v + 2] += nz; }
  }
  for (let i = 0; i < n.length; i += 3) {
    const len = Math.hypot(n[i], n[i + 1], n[i + 2]);
    if (len > 1e-6) { n[i] /= len; n[i + 1] /= len; n[i + 2] /= len; } else { n[i + 1] = 1; }
  }
  return n;
}

// ---------------------------------------------------------------------------
// 多实例路径的几何池：每个不同网格一份缓冲，只在 loadInstances 里建/传一次。
// 池按 meshIndex 索引，实例只存一个下标——"同一个树网格摆 300 份"在这里就是
// 300 条复用同一条缓冲的记录，显存和上传次数都不随实例数增长。
// ---------------------------------------------------------------------------
const poolKey = (d) => `${d.path || d.name || ""}|${d.vertexCount}|${d.indexCount}|${d.hasNormals ? 1 : 0}|${d.hasUvs ? 1 : 0}`;

/// 合并重复网格定义。
///
/// 为什么要合并：payload 允许"几个实例引用同一个网格定义"，但两边各自带一份同路径的
/// 网格数据时（地图导出常见），分开建就是两份一模一样的显存，白占一倍。
/// 合并的是**几何**，不是实例——矩阵仍旧一条一条留在实例表里。
///
/// 认不认"同一个"，看 key：路径 + 顶点数 + 索引数 + 有没有法线/UV。这几个字段
/// 决定了缓冲的字节布局，所以它们一致才能真正共用一份缓冲；只比路径是不够的，
/// 同名不同内容会被错并到一起（表现是某些实例画成另一个网格的形状）。
export function collapseMeshes(meshes) {
  const at = new Map();
  const unique = [];
  const toUnique = new Int32Array(meshes.length);
  for (let i = 0; i < meshes.length; i++) {
    const k = poolKey(meshes[i]);
    if (!at.has(k)) {
      at.set(k, unique.length);
      unique.push(meshes[i]);
    }
    toUnique[i] = at.get(k);
  }
  return { unique, toUnique };
}

/// 把一个网格的数据解包 + 上传，产出池里的一条记录。上传只在这里发生一次。
/// 同时把 CPU 侧数组一并交出去：单网格路径要往自己的专用缓冲里再传一遍，
/// 少解一次包（解包要过 atob，大模型上是实打实的开销）。
function uploadMesh(gl, data) {
  const { bytes, layout } = validateMesh(data);
  const vc = layout.vertexCount;
  const view = (at, n, Ctor) => new Ctor(bytes.buffer, bytes.byteOffset + at, n);
  const positions = view(layout.positions.at, vc * 3, Float32Array);
  let normals = layout.normals ? view(layout.normals.at, vc * 3, Float32Array) : null;
  const indices = view(layout.indices.at, layout.indexCount, Uint16Array);
  if (!normals) normals = faceNormals(positions, indices);

  const uvs = layout.uvs ? view(layout.uvs.at, vc * 2, Float32Array) : null;
  const buf = { pos: gl.createBuffer(), nrm: gl.createBuffer(), idx: gl.createBuffer(), uv: layout.uvs ? gl.createBuffer() : null };
  gl.bindBuffer(gl.ARRAY_BUFFER, buf.pos);
  gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER, buf.nrm);
  gl.bufferData(gl.ARRAY_BUFFER, normals, gl.STATIC_DRAW);
  if (uvs) {
    gl.bindBuffer(gl.ARRAY_BUFFER, buf.uv);
    gl.bufferData(gl.ARRAY_BUFFER, uvs, gl.STATIC_DRAW);
  }
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, buf.idx);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);

  return { buf, positions, normals, indices, uvs, ic: layout.indexCount, vertexCount: vc };
}

/// 从上传结果推出一份"可画的网格"记录。单网格和多实例共用，保证两边的
/// center/size 口径一样——两处各写一遍迟早会算出两个不一样的家。
function viewOf(geo, data) {
  const [mn, mx] = [data.bboxMin, data.bboxMax];
  return {
    ic: geo.ic,
    center: [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2],
    size: Math.max(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2], 1e-3),
    bboxMin: mn,
    bboxMax: mx,
    path: data.path,
  };
}

/// 全体实例的世界包围盒。用网格自己的局部盒 × 实例矩阵逐个并起来，
/// 而不是拿某个网格的局部盒充数——地图的落点全在实例矩阵里。
///
/// 引用的池下标不在池里（数据脏了）就跳过这一个：少算一个实例最多让相机
/// 的取景少一点点，拿 NaN 或 0 去凑则会算出"看着正常、其实是错的"盒子。
export function instancedBounds(pool, inst) {
  const acc = im.boundsAccumulator();
  for (let i = 0; i < inst.count; i++) {
    const geo = pool[inst.meshIndex[i]];
    if (!geo) continue;
    acc.addBox(inst.model.subarray(i * 16, i * 16 + 16), geo.bboxMin, geo.bboxMax);
  }
  return acc.result();
}

/// 点选用的每实例世界盒。
///
/// 这里老实用了"以盒心为中心、以被变换后最长边为棱长"的**外接正方体**，
/// 而不是精确的旋转盒：地图里绝大多数摆放只含绕 Y 转 + 平移，这个立方体
/// 和真实盒差得不多，而点选本来就只需要"大概最近的那一个"。
/// 代价是相邻的树/房子会互相遮挡得比真实情况更早（见 pickAt 的说明）。
export function instancedPickBounds(pool, inst) {
  const out = new Array(inst.count);
  for (let i = 0; i < inst.count; i++) {
    const geo = pool[inst.meshIndex[i]];
    const m = inst.model.subarray(i * 16, i * 16 + 16);
    const acc = im.boundsAccumulator();
    acc.addBox(m, geo.bboxMin, geo.bboxMax);
    const b = acc.result();
    const half = Math.max(b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2], 1e-4) / 2;
    out[i] = {
      bound: {
        min: [b.center[0] - half, b.center[1] - half, b.center[2] - half],
        max: [b.center[0] + half, b.center[1] + half, b.center[2] + half],
      },
    };
  }
  return out;
}

/// 蒙皮顶点数组的整备：校验（数组形状、长度、全有限）并摊平成 f32。
/// 校验不过回 null——调用方静默拒绝，画布停在上一帧的姿势，
/// 绝不能把坏数据灌进 GPU 画出一个鬼影。单网格 setPose 与整组
/// setPartPose 共用这一份，两条路的「不合格不进显存」只有一个来源。
function poseFlat(positions, vertexCount) {
  if (!Array.isArray(positions) || positions.length !== vertexCount) return null;
  for (const p of positions) {
    if (!Array.isArray(p) || p.length !== 3) return null;
    for (let i = 0; i < 3; i++) if (!Number.isFinite(p[i])) return null;
  }
  const flat = new Float32Array(positions.length * 3);
  let o = 0;
  for (const p of positions) {
    flat[o++] = p[0];
    flat[o++] = p[1];
    flat[o++] = p[2];
  }
  return flat;
}

/// 整组部件的世界包围盒：部件共用一副骨架 = 同一模型空间，把各自的局部盒
/// 直接并起来就是取景框（单件那样拿 parts[0] 的盒子充数会让其余几件出画）。
/// 盒子缺了/不有限的件跳过——少算一件最多取景偏一点，拿 NaN 凑则是全黑。
/// @returns {{ center: number[], size: number }}
export function partsUnionBounds(list) {
  const mn = [Infinity, Infinity, Infinity];
  const mx = [-Infinity, -Infinity, -Infinity];
  let any = false;
  for (const p of Array.isArray(list) ? list : []) {
    const a = p && p.bboxMin;
    const b = p && p.bboxMax;
    if (!Array.isArray(a) || !Array.isArray(b) || a.length < 3 || b.length < 3) continue;
    if (!a.concat(b).every(Number.isFinite)) continue;
    any = true;
    for (let k = 0; k < 3; k++) {
      mn[k] = Math.min(mn[k], a[k]);
      mx[k] = Math.max(mx[k], b[k]);
    }
  }
  if (!any) return { center: [0, 0, 0], size: 1 };
  const size = Math.max(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2], 1e-3);
  return { center: [(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, (mn[2] + mx[2]) / 2], size };
}

export class MeshViewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext("webgl", { antialias: true });
    if (!this.gl) throw new Error("这台机器开不了 WebGL，看不到 3D 预览");
    // 预览放大/窗口尺寸变化后要重算视口与投影：draw() 里会 syncViewport，
    // 这里只负责在被通知时补画一帧。
    window.addEventListener("tlbb:viewer-resize", () => this.draw());
    window.addEventListener("resize", () => this.draw());

    const gl = this.gl;
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      throw new Error("着色器链接失败：" + gl.getProgramInfoLog(prog));
    }
    this.prog = prog;
    this.at = { pos: gl.getAttribLocation(prog, "aPosition"), nrm: gl.getAttribLocation(prog, "aNormal"), uv: gl.getAttribLocation(prog, "aUv") };
    this.un = {
      mv: gl.getUniformLocation(prog, "uModelView"),
      pj: gl.getUniformLocation(prog, "uProjection"),
      inst: gl.getUniformLocation(prog, "uInstance"),
      nrm: gl.getUniformLocation(prog, "uNormalMat"),
      use: gl.getUniformLocation(prog, "uUseInst"),
      tex: gl.getUniformLocation(prog, "uTex"),
      useTex: gl.getUniformLocation(prog, "uUseTex"),
      mask: gl.getUniformLocation(prog, "uMask"),
      useMask: gl.getUniformLocation(prog, "uUseMask"),
      unlit: gl.getUniformLocation(prog, "uUnlit"),
      light: gl.getUniformLocation(prog, "uLight"),
    };
    gl.useProgram(prog);
    gl.uniform1i(this.un.tex, 0);
    gl.uniform1i(this.un.mask, 1);
    // 老路径用的四个专用缓冲：单网格时不动，行为和以前一样。
    // uv 必须也在专用缓冲里：load() 换数据时若只换三个，UV 就永远进不了
    // 绘制路径（drawSingle 的 texReady 分支拿不到 buf.uv，套贴图永远无效）。
    this.buf = { pos: gl.createBuffer(), nrm: gl.createBuffer(), idx: gl.createBuffer(), uv: gl.createBuffer() };

    // 连线程序起不来就只少画线，灰模照旧。构造函数不能因为这条附加层抛掉整个预览。
    this.lineProg = null;
    this.lineAt = -1;
    this.lineUn = null;
    this.boneBuf = null;
    this.bonePtsBuf = null;
    this.hlBuf = null;
    this.hlPtsBuf = null;
    this.boneCount = 0;
    this.bonePtCount = 0;
    this.hlCount = 0;
    this.hlPtCount = 0;
    this.prepareBoneLines(gl);

    // 多实例路径的几何池：每个**不同网格**一份缓冲，在 loadInstances 里上传一次。
    // 绝不每帧 bufferData，也绝不为每个实例建一个 buffer——后者在几千实例下是
    // 几千个 GL 对象 + 每帧几千次 bind，纯属自我惩罚。
    this.pool = [];
    this.inst = null;
    this.tex = null;
    this.texReady = false;
    this.texLayers = [];
    this.layerSeq = 0;
    this.pickBound = null;

    this.home = { dist: 3, rx: -0.25, ry: 0.6 };
    this.cam = { ...this.home, trx: this.home.rx, try: this.home.ry, tdist: this.home.dist };
    this.drag = null;
    this.raf = 0;
    this.mesh = null;
    /// 只为诊断用的子网格切片：null = 全画；N = 只画第 N 个子网格。
    this.faceRange = null;
    // 整组部件路径：每件一份独立缓冲，loadParts 建、unloadParts 收。
    // 与单网格 / 多实例互斥——同一时刻只有一种东西在画。
    this.parts = null;
    this.partsSeq = 0;
    this.bindEvents();
  }

  bindEvents() {
    const c = this.canvas;
    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      c.parentElement.classList.add("dragging");
      this.drag = { x: e.clientX, y: e.clientY };
    });
    c.addEventListener("pointermove", (e) => {
      if (!this.drag) return;
      this.cam.try += (e.clientX - this.drag.x) * 0.01;
      this.cam.trx = Math.max(-1.55, Math.min(1.55, this.cam.trx + (e.clientY - this.drag.y) * 0.01));
      this.drag = { x: e.clientX, y: e.clientY };
      this.start();
    });
    const release = () => {
      this.drag = null;
      // 画布可能在拖拽途中被换内容摘出文档（浏览树里换文件），
      // parentElement 已为 null，别在这里抛错。
      if (c.isConnected) c.parentElement.classList.remove("dragging");
      this.start(); // 松手后还要把惯性补完
    };
    c.addEventListener("pointerup", release);
    c.addEventListener("pointercancel", release);
    c.addEventListener("wheel", (e) => {
      if (!this.mesh && !this.inst && !this.parts) return; // 还没加载模型时让页面正常滚
      e.preventDefault();
      const k = e.deltaY > 0 ? 1.12 : 1 / 1.12;
      this.cam.tdist = Math.max(this.limits.min, Math.min(this.limits.max, this.cam.tdist * k));
      this.start();
    }, { passive: false });
    c.addEventListener("dblclick", () => {
      this.reset();
      this.start();
    });
    window.addEventListener("resize", () => this.resize());
    // 显卡驱动重置后 draw 会静默变成空操作，画布永久黑屏——必须接住并说一句话。
    c.addEventListener("webglcontextlost", (e) => {
      e.preventDefault();
      this.stop();
      // 上下文没了，缓冲和 program 都成了废引用：多实例与整组两条路径的
      // 状态必须一并清掉，不然"buffer 还在、其实早就没了"会一路带进下一次 draw。
      this.mesh = null;
      this.inst = null;
      this.pool = [];
      this.parts = null;
      this.pickBound = null;
      this.boneCount = 0;
      this.bonePtCount = 0;
      this.hlCount = 0;
      this.hlPtCount = 0;
      if (this.onlost) this.onlost();
    });
  }

  reset() {
    this.cam.trx = this.home.rx;
    this.cam.try = this.home.ry;
    this.cam.tdist = this.home.dist;
  }

  /// uUseInst 的唯一写入口。让"当前画的是哪种"只有一个来源，
  /// 也就不存在 load() 之后忘了把开关掰回去这种错。
  useInstanced(on) {
    // uniform 只认**当前 program** 的 location。load 阶段还没有任何绘制发生过，
    // 不先 useProgram 这句就是 INVALID_OPERATION 静默空操作——第一次打开地图时
    // 控制台就是这么报的。绑定一下，这条设置才真的算设置。
    const gl = this.gl;
    gl.useProgram(this.prog);
    gl.uniform1f(this.un.use, on ? 1 : 0);
  }

  syncViewport() {
    const dpr = window.devicePixelRatio || 1;
    const r = this.canvas.getBoundingClientRect();
    const w = Math.max(1, Math.round(r.width * dpr));
    const h = Math.max(1, Math.round(r.height * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.gl.viewport(0, 0, w, h);
  }

  resize() {
    this.syncViewport();
    this.start();
  }

  /// 套一张图到整只网格：人工确认/试贴走这条；分层贴图不走这里。
  setTexture(dataUrl) {
    const gl = this.gl;
    this.clearTextureLayers();
    const my = this.layerSeq;
    this.texReady = false;
    loadImage(dataUrl).then((img) => {
      if (my !== this.layerSeq) return;
      if (this.tex) gl.deleteTexture(this.tex);
      this.tex = uploadTexture(gl, img);
      this.texReady = true;
      this.draw();
    }).catch(() => {});
  }

  /// 分层贴图：每层一段子网格、自己的颜色图（可选 mask）。基础层不混合，
  /// 特效层用 `SRC_ALPHA, ONE` 叠加——这正是 `.mtl` 里 `add_trans` 的意思。
  setTextureLayers(layers) {
    const gl = this.gl;
    this.clearTextureLayers();
    this.texReady = false;
    const my = this.layerSeq;
    const list = (Array.isArray(layers) ? layers : []).filter(
      (l) => l && l.color && l.color.png && Number(l.faceCount) > 0,
    );
    const jobs = list.map(async (l) => {
      let img;
      try {
        img = await loadImage(l.color.png);
      } catch {
        return null;
      }
      let mask = null;
      if (l.mask && l.mask.png) {
        try {
          mask = await loadImage(l.mask.png);
        } catch {
          mask = null;
        }
      }
      if (my !== this.layerSeq) {
        return null;
      }
      return {
        tex: uploadTexture(gl, img),
        mask: mask ? uploadTexture(gl, mask) : null,
        start: Math.max(0, Number(l.faceStart) || 0) * 3,
        count: Math.max(0, Number(l.faceCount) || 0) * 3,
        blend: l.blend === "add" ? "add" : "opaque",
        slot: l.slot || (l.color && l.color.slot) || "",
        maskSlot: (l.mask && l.mask.slot) || "",
      };
    });
    Promise.allSettled(jobs).then((results) => {
      const ready = results.filter((r) => r.status === "fulfilled" && r.value).map((r) => r.value);
      if (my !== this.layerSeq) {
        for (const l of ready) {
          if (l.tex) gl.deleteTexture(l.tex);
          if (l.mask) gl.deleteTexture(l.mask);
        }
        return;
      }
      this.texLayers = ready;
      this.soloLayer = null;
      this.draw();
    });
  }

  /// 分层模式下只换某一条槽位的图（auto 卡「套上看看」用）：不把整只网格盖成一张。
  /// 槽名对不上任何一层就回 false，调用方才走单张老路。
  setLayerTexture(slotName, dataUrl) {
    const gl = this.gl;
    const want = String(slotName || "").toLowerCase();
    if (!want || !this.texLayers.length) return false;
    const colorHit = this.texLayers.find((l) => String(l.slot).toLowerCase() === want);
    const maskHit = this.texLayers.find((l) => String(l.maskSlot).toLowerCase() === want);
    if (!colorHit && !maskHit) return false;
    const my = this.layerSeq;
    loadImage(dataUrl).then((img) => {
      if (my !== this.layerSeq) return;
      const tex = uploadTexture(gl, img);
      if (colorHit) {
        if (colorHit.tex) gl.deleteTexture(colorHit.tex);
        colorHit.tex = tex;
      } else if (maskHit) {
        if (maskHit.mask) gl.deleteTexture(maskHit.mask);
        maskHit.mask = tex;
      }
      this.draw();
    }).catch(() => {});
    return true;
  }

  /// 只看某一层（核顺序用）：`null` = 全部层。只影响绘制，不动贴图数据。
  /// 分层是「哪段几何配哪张图」的推断时，这个开关让人一眼看出配错没配错。
  setLayerSolo(index) {
    this.soloLayer = index == null ? null : Number(index);
    this.draw();
  }

  /// 整组预览下只看当前件的某一层。`layerIndex=null` 恢复全部。
  setPartLayerSolo(index, layerIndex) {
    const part = this.parts && this.parts[index];
    if (!part) return false;
    part.solo = layerIndex == null ? null : Number(layerIndex);
    this.draw();
    return true;
  }

  clearTextureLayers() {
    const gl = this.gl;
    this.layerSeq++;
    for (const l of this.texLayers) {
      if (l.tex) gl.deleteTexture(l.tex);
      if (l.mask) gl.deleteTexture(l.mask);
    }
    this.texLayers = [];
  }

  clearTexture() {
    this.clearTextureLayers();
    this.clearPartTextures();
    this.texReady = false;
    this.draw();
  }

  /// 整组预览：给第 i 件装它自己的分层贴图。与单网格的 setTextureLayers 同构，
  /// 但每件独立，互不覆盖——黄蜂的身体和翅膀各有各的图。
  setPartLayers(index, layers) {
    const gl = this.gl;
    const part = this.parts && this.parts[index];
    if (!part) return false;
    this.clearOnePartTextures(part);
    part.layerToken = (part.layerToken || 0) + 1;
    const token = part.layerToken;
    const my = this.partsSeq;
    const list = (Array.isArray(layers) ? layers : []).filter(
      (l) => l && l.color && l.color.png && Number(l.faceCount) > 0,
    );
    const jobs = list.map(async (l) => {
      let img;
      try {
        img = await loadImage(l.color.png);
      } catch {
        return null;
      }
      let mask = null;
      if (l.mask && l.mask.png) {
        try {
          mask = await loadImage(l.mask.png);
        } catch {
          mask = null;
        }
      }
      if (my !== this.partsSeq || part.layerToken !== token) return null;
      return {
        tex: uploadTexture(gl, img),
        mask: mask ? uploadTexture(gl, mask) : null,
        start: Math.max(0, Number(l.faceStart) || 0) * 3,
        count: Math.max(0, Number(l.faceCount) || 0) * 3,
        blend: l.blend === "add" ? "add" : "opaque",
        slot: l.slot || (l.color && l.color.slot) || "",
        maskSlot: (l.mask && l.mask.slot) || "",
      };
    });
    Promise.allSettled(jobs).then((results) => {
      const ready = results.filter((r) => r.status === "fulfilled" && r.value).map((r) => r.value);
      if (my !== this.partsSeq || part.layerToken !== token) {
        for (const l of ready) {
          if (l.tex) gl.deleteTexture(l.tex);
          if (l.mask) gl.deleteTexture(l.mask);
        }
        return;
      }
      part.layers = ready;
      part.solo = null;
      this.draw();
    });
    return true;
  }

  /// 分层模式下只换某一件的某一条槽位（auto 卡「套上看看」）。
  setPartLayerTexture(index, slotName, dataUrl) {
    const gl = this.gl;
    const part = this.parts && this.parts[index];
    const want = String(slotName || "").toLowerCase();
    if (!part || !want || !part.layers || !part.layers.length) return false;
    const colorHit = part.layers.find((l) => String(l.slot).toLowerCase() === want);
    const maskHit = part.layers.find((l) => String(l.maskSlot).toLowerCase() === want);
    if (!colorHit && !maskHit) return false;
    const my = this.partsSeq;
    loadImage(dataUrl).then((img) => {
      if (my !== this.partsSeq || part !== this.parts[index]) return;
      const tex = uploadTexture(gl, img);
      if (colorHit) {
        if (colorHit.tex) gl.deleteTexture(colorHit.tex);
        colorHit.tex = tex;
      } else {
        if (maskHit.mask) gl.deleteTexture(maskHit.mask);
        maskHit.mask = tex;
      }
      this.draw();
    }).catch(() => {});
    return true;
  }

  /// 整张候选试贴：只套到这一件，别的件不受影响。
  setPartSingleTexture(index, dataUrl) {
    const gl = this.gl;
    const part = this.parts && this.parts[index];
    if (!part) return false;
    this.clearOnePartTextures(part);
    const my = this.partsSeq;
    loadImage(dataUrl).then((img) => {
      if (my !== this.partsSeq || part !== this.parts[index]) return;
      part.singleTex = uploadTexture(gl, img);
      part.singleReady = true;
      this.draw();
    }).catch(() => {});
    return true;
  }

  clearOnePartTextures(part) {
    const gl = this.gl;
    for (const l of part.layers || []) {
      if (l.tex) gl.deleteTexture(l.tex);
      if (l.mask) gl.deleteTexture(l.mask);
    }
    part.layers = [];
    if (part.singleTex) gl.deleteTexture(part.singleTex);
    part.singleTex = null;
    part.singleReady = false;
    part.layerToken = (part.layerToken || 0) + 1;
  }

  clearPartTextures() {
    this.partsSeq++;
    for (const p of this.parts || []) this.clearOnePartTextures(p);
    this.draw();
  }

  /// 诊断用：只画指定子网格；传 null 回到整只网格。面数来自 mesh_data.faceCounts。
  setSubmeshOnly(index) {
    if (index === null || index === undefined) {
      this.faceRange = null;
      this.draw();
      return true;
    }
    const counts = (this.mesh && this.mesh.faceCounts) || [];
    if (!Number.isInteger(index) || index < 0 || index >= counts.length) return false;
    let start = 0;
    for (let i = 0; i < index; i++) start += counts[i] * 3;
    this.faceRange = { start, count: counts[index] * 3 };
    this.draw();
    return true;
  }

  /// 把「按某帧动作摆好的顶点」写进现有位置缓冲（动作页蒙皮预览专用）。
  /// 只在单网格路径可用：多实例的几何住在池里，那是地图的静态形状，不该被逐帧改写；
  /// 整组部件走 setPartPose（与这里互斥：parts 在架上时 mesh 必为 null）。
  ///
  /// 数据不合格（长度对不上 / 坐标不是有限数）静默拒绝并回 false——蒙皮复合出了
  /// NaN 时画布顶多停在上一帧的姿势，绝不能把坏数据灌进 GPU 画出一个鬼影。
  /// 只用 bufferSubData 改内容，不建新缓冲：游标一拖就是一次调用，每帧
  /// bufferData 等于把 STATIC_DRAW 当垃圾桶用。
  setPose(positions) {
    if (!this.mesh || this.inst || this.parts) return false;
    const flat = poseFlat(positions, this.mesh.vertexCount);
    if (!flat) return false;
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.pos);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, flat);
    this.draw();
    return true;
  }

  // ---- 整组部件路径（多件套网格一起摆：每件一份独立缓冲，同一 program 依次画）----
  //
  // 与单网格 / 多实例互斥：loadParts 架上 parts、把 mesh/inst 置空；
  // load / loadInstances 反过来先收 parts。三条路谁在画只看这三个字段，
  // 不存在"画了单网格又画部件"的中间态。

  /// 整组装载。items = meshData 回包数组（与单网格 load 的 data 同一形状，
  /// 每件自带 bboxMin/bboxMax 供取景并盒）。任一件数据校验不过就整批不换——
  /// 旧的几件原样留着，调用方按件降级，画布不会变成半个黑屏。
  loadParts(items) {
    const gl = this.gl;
    const list = Array.isArray(items) ? items : [];
    if (!list.length) throw new Error("整组预览一件网格都没有，画不出东西");
    // 先建后拆：全部建成功才收旧的，中途抛错旧画面还在。
    const fresh = [];
    try {
      for (const data of list) {
        const geo = uploadMesh(gl, data);
        fresh.push({
          buf: geo.buf,
          ic: geo.ic,
          vertexCount: geo.vertexCount,
          layers: [],
          singleReady: false,
          singleTex: null,
          ...viewOf(geo, data),
        });
      }
    } catch (e) {
      // uv 段可能没建（无 UV 的网格里它是 null），deleteBuffer 对 null 是空操作。
      for (const p of fresh) for (const b of [p.buf.pos, p.buf.nrm, p.buf.idx, p.buf.uv]) if (b) gl.deleteBuffer(b);
      throw e;
    }
    this.unloadParts();
    this.parts = fresh;
    this.partsSeq++;
    this.clearTextureLayers();
    this.texReady = false;
    this.mesh = null;
    this.inst = null;
    this.pickBound = null;
    // 骨线是单网格绑定姿态的事，整组路径不摆它。
    this.setBoneLines(null);
    // 取景用整组并盒：单件的盒子会把其余几件切出画面。
    this.applyFrame(partsUnionBounds(fresh));
    this.trackAllocation();
    this.syncViewport();
    this.draw(); // 先画定一帧，理由同 load
  }

  /// 每份部件缓冲整体换新/清空都从这里走，四个缓冲一个不漏（含可能为 null 的 uv）。
  unloadParts() {
    const gl = this.gl;
    this.partsSeq++;
    for (const p of this.parts || []) {
      for (const b of [p.buf.pos, p.buf.nrm, p.buf.idx, p.buf.uv]) if (b) gl.deleteBuffer(b);
      for (const l of p.layers || []) {
        if (l.tex) gl.deleteTexture(l.tex);
        if (l.mask) gl.deleteTexture(l.mask);
      }
      if (p.singleTex) gl.deleteTexture(p.singleTex);
    }
    this.parts = null;
  }

  /// 整组收摊（切资产 / 清页时调用）：缓冲删掉、状态清空、重画一次——
  /// 画布上不该再留着上一只怪的最后一步。
  clearParts() {
    this.unloadParts();
    this.draw();
  }

  /// 把第 i 件「按某帧动作摆好的顶点」写进它自己的位置缓冲。
  /// 校验不过（没在整组路径 / 下标越界 / 顶点数或坐标不合格）静默回 false，
  /// 语义与 setPose 一致：那一帧没摆上就停在上一帧，不硬画。
  setPartPose(i, positions) {
    const parts = this.parts;
    if (!parts || !Number.isInteger(i) || i < 0 || i >= parts.length) return false;
    const flat = poseFlat(positions, parts[i].vertexCount);
    if (!flat) return false;
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, parts[i].buf.pos);
    gl.bufferSubData(gl.ARRAY_BUFFER, 0, flat);
    this.draw();
    return true;
  }

  /// bones 可选。不传、空表、或线段里没有可画的点时，画面与只传网格时一致。
  load(data, bones) {
    const gl = this.gl;
    // 长度与偏移由 lib/meshLayout.js 统一校验（有 node --test 盯着）：
    // 声明和实际字节数不符时必须拒绝，绝不能把错数据画得像个模型。
    // 解包只走 uploadMesh 一处：单网格和多实例各写一份解包，迟早有一边跑偏。
    const geo = uploadMesh(gl, data);
    // uploadMesh 用的是临时缓冲，这里把它换到老路径那组专用缓冲上，
    // 然后立刻回收临时的那一份——不然每 load 一次就漏四个 buffer。
    const tmp = geo.buf;
    geo.buf = this.buf;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.pos);
    gl.bufferData(gl.ARRAY_BUFFER, geo.positions, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.nrm);
    gl.bufferData(gl.ARRAY_BUFFER, geo.normals, gl.STATIC_DRAW);
    // UV 段必须跟着进专用缓冲：套贴图能不能生效，取决于 drawSingle 时
    // buf.uv 里有没有数据（没有就永远退化成灰模，候选卡上的图成了摆设）。
    if (geo.uvs) {
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.uv);
      gl.bufferData(gl.ARRAY_BUFFER, geo.uvs, gl.STATIC_DRAW);
    }
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.buf.idx);
    // 目标必须是 ELEMENT：上一行刚把 ELEMENT 绑到 this.buf.idx，这里却写 ARRAY_BUFFER
    // 的话，索引字节会灌进当时还绑着的 UV 槽位、索引缓冲永远空着——drawElements 每帧
    // 报 1282、灰模一个三角形都出不来（e98f449 引入、2026-10-07 验收现场抓的回归）。
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, geo.indices, gl.STATIC_DRAW);
    for (const b of [tmp.pos, tmp.nrm, tmp.idx, tmp.uv]) if (b) gl.deleteBuffer(b);

    this.unloadPool(); // 从多实例切回单网格：地图的几何池该收掉了
    this.unloadParts(); // 与整组路径互斥：老路径一上来，部件必须收干净
    // vertexCount 原本不在 viewOf 的产出里（那是单/多实例共用的口径函数），
    // 蒙皮预览的 setPose 要拿它核对回包顶点数——加在这里不动共享口径。
    this.mesh = {
      ...viewOf(geo, data),
      vertexCount: geo.vertexCount,
      faceCounts: Array.isArray(data.faceCounts) ? data.faceCounts : [],
    };
    this.faceRange = null;
    this.inst = null;
    this.pickBound = null;
    // 单网格的"家"就是它自己的局部盒（跟扩展前一样）。这里不走实例那套
    // 世界包围盒：实例数为 1 且矩阵是单位阵，结果完全等价，多绕一圈只会
    // 让人以为单网格也支持变换。
    this.applyFrame({ center: this.mesh.center, size: this.mesh.size });
    this.trackAllocation();
    // 线段上传失败只是不画线。网格已经进了缓冲，不能让这一步把灰模一起拆掉。
    try {
      this.setBoneLines(bones);
    } catch {
      this.boneCount = 0;
      this.bonePtCount = 0;
    }
    this.syncViewport();
    this.draw(); // 先画定一帧：窗口没聚焦时 rAF 会被挂起，否则首帧要等很久
  }

  /// 几何池整体换新/清空都从这里走，保证四个缓冲一个不漏。
  /// uv 也在池里（带贴图坐标的网格每份一个），漏了它就是每次换图漏一批 GL 对象；
  /// 没有 UV 的网格这里存的是 null，deleteBuffer 对 null 是空操作。
  unloadPool() {
    const gl = this.gl;
    for (const p of this.pool) for (const b of [p.buf.pos, p.buf.nrm, p.buf.idx, p.buf.uv]) gl.deleteBuffer(b);
    this.pool = [];
  }

  /// load / loadInstances 都在**画第一帧之前**调一次：此刻还没有任何需要保护的
  /// 画面，设置 uUseInst 不会被谁挡住，渲染态也就不会在两条路径之间串。
  trackAllocation() {
    this.useInstanced(Boolean(this.inst));
    this.clearTextureLayers();
    this.texReady = false;
  }

  /// 相机的家 / 近远裁剪 / 缩放上下限统一按传入的**世界**包围盒来定。
  ///
  /// 单网格路径传的就是那个网格自己的盒子（等价于以前的行为）；
  /// 多实例路径传全体实例的世界盒子——否则地图一打开，相机会停在某个房子的
  /// 局部原点附近，近裁剪面还会把整片地形切掉。
  applyFrame(bounds) {
    const size = Math.max(bounds.size, 1e-3);
    const c = bounds.center;
    this.frame = { center: [c[0], c[1], c[2]], size };
    this.home.dist = size * 2.1;
    this.limits = { min: size * 0.02, max: size * 8 };
    this.reset();
    this.cam.dist = this.home.dist;
    // 近裁剪面必须跟着**世界尺度**走：地图跨几万单位、单个房子才几十，
    // 用网格的局部 size 定 near 会让远离原点的东西整片被切掉（被切掉的
    // 部分既不报错也不变黑，只是"就是没有"，最难查）。
    this.near = Math.max(size * 0.002, 0.01);
    this.far = size * 12;
  }

  /// 多实例装载。payload = { meshes: [meshData...], instances: [{ meshIndex, matrix }] }，
  /// 其中 matrix 是从 `.scene` 记录**原样直读**的 16 个 f32，已是 GL 布局（平移在 [12..14]）。
  loadInstances(payload) {
    const gl = this.gl;
    const meshes = (payload && payload.meshes) || [];
    const instances = (payload && payload.instances) || [];
    if (!meshes.length) throw new Error("这份地图没有可用的网格数据");
    if (!instances.length) throw new Error("这份地图里一个实例都没有，画不出东西");

    // 先把几何池换成新的一份，成功了再收掉旧的——中途抛错时旧池还在，
    // 界面顶多还是上一张图，而不会变成一个删光缓冲的黑屏。
    const { unique, toUnique } = collapseMeshes(meshes);
    const fresh = [];
    try {
      for (const m of unique) {
        const geo = uploadMesh(gl, m);
        fresh.push({ ...viewOf(geo, m), buf: geo.buf, bboxMin: m.bboxMin, bboxMax: m.bboxMax, path: m.path });
      }
    } catch (e) {
      // 建到一半失败：把已经建好的几个删掉，旧池原封不动继续用。
      // uv 段可能没建（无 UV 的网格里它是 null），deleteBuffer 对 null 是空操作。
      for (const p of fresh) for (const b of [p.buf.pos, p.buf.nrm, p.buf.idx, p.buf.uv]) gl.deleteBuffer(b);
      throw e;
    }
    this.unloadPool();
    this.unloadParts(); // 与整组路径互斥
    this.pool = fresh;

    // 实例表：矩阵预先转置 + 预先推法线矩阵，绘制时只剩一次 uniformMatrix 调用。
    // 注意 instances 里的 meshIndex 指的是**原** meshes 顺序，要映射到池下标。
    this.inst = im.expandInstances(instances, meshes.length);
    for (let i = 0; i < this.inst.count; i++) this.inst.meshIndex[i] = toUnique[this.inst.meshIndex[i]];

    this.bounds = instancedBounds(fresh, this.inst);
    this.pickBound = instancedPickBounds(fresh, this.inst);
    this.mesh = null;
    this.setBoneLines(null);
    this.applyFrame(this.bounds);
    this.trackAllocation();
    this.syncViewport();
    this.draw();
  }

  /// 场景光照强度（1 = 默认）。地图页按 `.sfl` 的环境光填；其它页面不动。
  setLight(v) {
    this.light = Number.isFinite(v) ? Math.min(1.15, Math.max(0.75, v)) : null;
    this.draw();
  }

  /// 地图页：清屏透明，露出画布背后的天色渐变（颜色取自客户端 `.sfl`）。
  setBackdrop(on) {
    this.backdrop = !!on;
    this.draw();
  }

  /// 地表编码格底图：一张带透明度的贴图铺在 XZ 平面上（**不是地形高度**）。
  setGround(img, rect) {
    this.ground = img && rect
      ? { img, rect, token: (this.groundToken = (this.groundToken || 0) + 1) }
      : null;
    this.draw();
  }

  /// 相机还在动就继续下一帧，停稳就自己收工——静态展示没必要一直占着 GPU。
  start() {
    if (this.raf) return;
    const frame = () => {
      const moving = this.draw();
      if (moving || this.drag) this.raf = requestAnimationFrame(frame);
      else this.raf = 0;
    };
    this.raf = requestAnimationFrame(frame);
  }

  stop() {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  draw() {
    const gl = this.gl;
    this.syncViewport();
    gl.clearColor(0.055, 0.067, 0.078, this.backdrop ? 0 : 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!this.mesh && !this.inst && !this.parts) return false;
    gl.enable(gl.DEPTH_TEST);

    const frame = this.frame || { center: [0, 0, 0], size: 1 };
    const c = this.cam;
    const eps = frame.size * 1e-4;
    const settled = Math.abs(c.tdist - c.dist) < eps && Math.abs(c.trx - c.rx) < 1e-4 && Math.abs(c.try - c.ry) < 1e-4;
    if (settled) {
      c.dist = c.tdist;
      c.rx = c.trx;
      c.ry = c.try;
    } else {
      c.dist += (c.tdist - c.dist) * 0.18;
      c.rx += (c.trx - c.rx) * 0.22;
      c.ry += (c.try - c.ry) * 0.22;
    }

    const ctr = frame.center;
    let mv = mat4.identity();
    mv = mat4.mul(mv, mat4.translate(0, 0, -c.dist));
    mv = mat4.mul(mv, mat4.rotateX(c.rx));
    mv = mat4.mul(mv, mat4.rotateY(c.ry));
    mv = mat4.mul(mv, mat4.translate(-ctr[0], -ctr[1], -ctr[2]));
    this.view = mv; // 留给 pickAt 反投影用，正好是这一帧相机实际的取景矩阵

    const aspect = this.canvas.width / Math.max(1, this.canvas.height);
    this.aspect = aspect;
    const proj = mat4.perspective(FOV, aspect, this.near, this.far);
    gl.useProgram(this.prog);
    gl.uniformMatrix4fv(this.un.pj, false, proj);
    gl.uniformMatrix4fv(this.un.mv, false, mv);
    if (this.un.light) gl.uniform1f(this.un.light, this.light == null ? 1 : this.light);

    if (this.ground) this.drawGround(mv, proj);
    if (this.parts) {
      this.drawParts();
      this.drawBoneLines(mv, proj); // 动作页可叠骨线；没设过时 boneCount 为 0，空操作
    } else if (this.inst) {
      this.drawInstanced();
      this.drawPickBox(mv, proj);
    }
    else {
      this.drawSingle();
      this.drawBoneLines(mv, proj);
    }
    return !settled;
  }

  /// 地表编码格底图：4 顶点一块平面 + 一张透明贴图。缓冲只在换图时重建。
  drawGround(mv, proj) {
    const g = this.ground;
    if (!g) return;
    const gl = this.gl;
    if (!g.buf || g.builtToken !== g.token) {
      if (g.buf) for (const b of g.buf.all) gl.deleteBuffer(b);
      if (g.tex) gl.deleteTexture(g.tex);
      const { x0, z0, x1, z1, y } = g.rect;
      const pos = new Float32Array([x0, y, z0, x1, y, z0, x1, y, z1, x0, y, z1]);
      const nrm = new Float32Array([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]);
      const uv = new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]);
      const idx = new Uint16Array([0, 1, 2, 0, 2, 3]);
      const mk = (arr) => {
        const b = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, b);
        gl.bufferData(gl.ARRAY_BUFFER, arr, gl.STATIC_DRAW);
        return b;
      };
      const bp = mk(pos);
      const bn = mk(nrm);
      const bu = mk(uv);
      const bi = gl.createBuffer();
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, bi);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
      g.buf = { pos: bp, nrm: bn, uv: bu, idx: bi, all: [bp, bn, bu, bi] };
      g.tex = uploadTexture(gl, g.img);
      g.builtToken = g.token;
    }
    gl.useProgram(this.prog);
    gl.uniformMatrix4fv(this.un.pj, false, proj);
    gl.uniformMatrix4fv(this.un.mv, false, mv);
    gl.uniform1f(this.un.use, 0);
    gl.uniform1f(this.un.unlit, 0);
    gl.uniform1f(this.un.useMask, 0);
    gl.uniform1f(this.un.useTex, 1);
    gl.bindBuffer(gl.ARRAY_BUFFER, g.buf.pos);
    gl.enableVertexAttribArray(this.at.pos);
    gl.vertexAttribPointer(this.at.pos, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, g.buf.nrm);
    gl.enableVertexAttribArray(this.at.nrm);
    gl.vertexAttribPointer(this.at.nrm, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, g.buf.uv);
    gl.enableVertexAttribArray(this.at.uv);
    gl.vertexAttribPointer(this.at.uv, 2, gl.FLOAT, false, 0, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, g.tex);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.depthMask(false);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, g.buf.idx);
    gl.drawElements(gl.TRIANGLES, 6, gl.UNSIGNED_SHORT, 0);
    gl.depthMask(true);
    gl.disable(gl.BLEND);
    gl.uniform1f(this.un.useTex, 0);
  }

  /// 绑定姿态的线段。没有可画的点时立刻返回，不改程序、不改深度。
  /// 坐标已经是模型空间里的点，套用这一帧灰模用的同一套模型视图和投影。
  setBoneLines(payload) {
    this.boneCount = 0;
    this.bonePtCount = 0;
    this.hlCount = 0;
    this.hlPtCount = 0;
    if (!this.lineProg || !this.boneBuf) return;
    const pairs = boneLineVertices(payload);
    if (!pairs.length) return;
    const data = new Float32Array(pairs.length * 6);
    let o = 0;
    for (const [a, b] of pairs) {
      data[o++] = a[0];
      data[o++] = a[1];
      data[o++] = a[2];
      data[o++] = b[0];
      data[o++] = b[1];
      data[o++] = b[2];
    }
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.boneBuf);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    this.boneCount = pairs.length * 2;
    // 关节点：线段端点去重后画成点。1px 宽度的线在小画布里几乎看不见，
    // 有点才看得出每根骨头落在哪、树怎么分叉。
    const pts = [];
    const seen = new Set();
    for (const [a, b] of pairs) {
      for (const p of [a, b]) {
        const key = `${p[0]},${p[1]},${p[2]}`;
        if (seen.has(key)) continue;
        seen.add(key);
        pts.push(p[0], p[1], p[2]);
      }
    }
    if (this.bonePtsBuf && pts.length) {
      gl.bindBuffer(gl.ARRAY_BUFFER, this.bonePtsBuf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(pts), gl.STATIC_DRAW);
      this.bonePtCount = pts.length / 3;
    }
  }

  drawBoneLines(mv, proj) {
    if (!this.boneCount || !this.lineProg || !this.boneBuf || this.lineAt < 0) return;
    const gl = this.gl;
    gl.useProgram(this.lineProg);
    gl.uniformMatrix4fv(this.lineUn.mv, false, mv);
    gl.uniformMatrix4fv(this.lineUn.pj, false, proj);
    if (this.lineUn.color) gl.uniform4f(this.lineUn.color, 0.16, 0.88, 0.98, 1.0);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.boneBuf);
    gl.enableVertexAttribArray(this.lineAt);
    gl.vertexAttribPointer(this.lineAt, 3, gl.FLOAT, false, 0, 0);
    gl.disable(gl.DEPTH_TEST);
    gl.drawArrays(gl.LINES, 0, this.boneCount);
    if (this.bonePtCount && this.bonePtsBuf && this.lineUn.pt) {
      gl.uniform1f(this.lineUn.pt, 5 * (window.devicePixelRatio || 1));
      gl.bindBuffer(gl.ARRAY_BUFFER, this.bonePtsBuf);
      gl.vertexAttribPointer(this.lineAt, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.POINTS, 0, this.bonePtCount);
    }
    // 选中的骨：黄色叠在青线上面，最后画。
    if (this.hlCount && this.hlBuf && this.lineUn.color) {
      gl.uniform4f(this.lineUn.color, 1.0, 0.92, 0.25, 1.0);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.hlBuf);
      gl.vertexAttribPointer(this.lineAt, 3, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.LINES, 0, this.hlCount);
      // 1px 线段在纹理上不够醒目，端点再点两颗大一点的点。
      if (this.hlPtCount && this.hlPtsBuf && this.lineUn.pt) {
        gl.uniform1f(this.lineUn.pt, 9 * (window.devicePixelRatio || 1));
        gl.bindBuffer(gl.ARRAY_BUFFER, this.hlPtsBuf);
        gl.vertexAttribPointer(this.lineAt, 3, gl.FLOAT, false, 0, 0);
        gl.drawArrays(gl.POINTS, 0, this.hlPtCount);
      }
    }
    gl.enable(gl.DEPTH_TEST);
  }

  /// 骨架表里选中的那根骨：把与它相连的父子线段单独画黄。
  setBoneHighlight(pairs) {
    this.hlCount = 0;
    this.hlPtCount = 0;
    if (!this.lineProg || !this.hlBuf) return;
    const list = Array.isArray(pairs) ? pairs : [];
    if (list.length) {
      const data = new Float32Array(list.length * 6);
      const pts = [];
      const seen = new Set();
      let o = 0;
      for (const [a, b] of list) {
        data[o++] = a[0];
        data[o++] = a[1];
        data[o++] = a[2];
        data[o++] = b[0];
        data[o++] = b[1];
        data[o++] = b[2];
        for (const p of [a, b]) {
          const key = `${p[0]},${p[1]},${p[2]}`;
          if (seen.has(key)) continue;
          seen.add(key);
          pts.push(p[0], p[1], p[2]);
        }
      }
      const gl = this.gl;
      gl.bindBuffer(gl.ARRAY_BUFFER, this.hlBuf);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      this.hlCount = list.length * 2;
      if (this.hlPtsBuf && pts.length) {
        gl.bindBuffer(gl.ARRAY_BUFFER, this.hlPtsBuf);
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(pts), gl.STATIC_DRAW);
        this.hlPtCount = pts.length / 3;
      }
    }
    this.draw();
  }

  prepareBoneLines(gl) {
    let prog = null;
    try {
      prog = gl.createProgram();
      gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, BONE_VS));
      gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, BONE_FS));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(prog) || "骨头连线着色器链接失败");
      }
      this.lineProg = prog;
      this.lineAt = gl.getAttribLocation(prog, "aPosition");
      this.lineUn = {
        mv: gl.getUniformLocation(prog, "uModelView"),
        pj: gl.getUniformLocation(prog, "uProjection"),
        pt: gl.getUniformLocation(prog, "uPointSize"),
        color: gl.getUniformLocation(prog, "uColor"),
      };
      this.boneBuf = gl.createBuffer();
      this.bonePtsBuf = gl.createBuffer();
      this.hlBuf = gl.createBuffer();
      this.hlPtsBuf = gl.createBuffer();
    } catch {
      if (prog) gl.deleteProgram(prog);
      this.lineProg = null;
      this.lineAt = -1;
      this.lineUn = null;
      this.boneBuf = null;
      this.bonePtsBuf = null;
      this.hlBuf = null;
      this.hlPtsBuf = null;
      this.boneCount = 0;
      this.bonePtCount = 0;
      this.hlCount = 0;
      this.hlPtCount = 0;
    }
  }

  /// 单网格：与扩展前逐位一致——uUseInst=0，走缓冲里原样的顶点。
  drawSingle() {
    const gl = this.gl;
    gl.uniform1f(this.un.use, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.pos);
    gl.enableVertexAttribArray(this.at.pos);
    gl.vertexAttribPointer(this.at.pos, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.nrm);
    gl.enableVertexAttribArray(this.at.nrm);
    gl.vertexAttribPointer(this.at.nrm, 3, gl.FLOAT, false, 0, 0);
    const layerPath = this.texLayers.length > 0 && this.buf.uv;
    const singlePath = this.texReady && this.buf.uv && !layerPath;
    if (layerPath || singlePath) {
      gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.uv);
      gl.enableVertexAttribArray(this.at.uv);
      gl.vertexAttribPointer(this.at.uv, 2, gl.FLOAT, false, 0, 0);
      gl.uniform1f(this.un.useTex, 1);
    } else {
      gl.uniform1f(this.un.useTex, 0);
      gl.uniform1f(this.un.useMask, 0);
      gl.uniform1f(this.un.unlit, 0);
    }
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.buf.idx);
    if (layerPath) {
      for (const [li, l] of this.texLayers.entries()) {
        if (!l.count) continue;
        if (this.soloLayer != null && li !== this.soloLayer) continue;
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, l.tex);
        if (l.mask) {
          gl.activeTexture(gl.TEXTURE1);
          gl.bindTexture(gl.TEXTURE_2D, l.mask);
          gl.uniform1f(this.un.useMask, 1);
        } else {
          gl.uniform1f(this.un.useMask, 0);
        }
        if (l.blend === "add") {
          gl.enable(gl.BLEND);
          gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
          gl.depthMask(false);
          gl.enable(gl.POLYGON_OFFSET_FILL);
          gl.polygonOffset(-1, -1);
          gl.uniform1f(this.un.unlit, 1);
        } else {
          gl.disable(gl.BLEND);
          gl.depthMask(true);
          gl.disable(gl.POLYGON_OFFSET_FILL);
          gl.uniform1f(this.un.unlit, 0);
        }
        gl.drawElements(gl.TRIANGLES, l.count, gl.UNSIGNED_SHORT, l.start * 2);
      }
      gl.disable(gl.BLEND);
      gl.depthMask(true);
      gl.disable(gl.POLYGON_OFFSET_FILL);
      gl.uniform1f(this.un.useMask, 0);
      gl.uniform1f(this.un.unlit, 0);
      return;
    }
    if (singlePath) {
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, this.tex);
    }
    if (this.faceRange) {
      gl.drawElements(gl.TRIANGLES, this.faceRange.count, gl.UNSIGNED_SHORT, this.faceRange.start * 2);
    } else {
      gl.drawElements(gl.TRIANGLES, this.mesh.ic, gl.UNSIGNED_SHORT, 0);
    }
  }

  /// 地图道具的分层贴图：按**几何池路径**对号，与 setPartLayers 同构。
  /// 只给带 UV 的池子网格套图；没有计划的保持灰模。异步加载完成后才落层，
  /// 中途换池（`this.pool !== pool`）或本网格又换了一批计划（token）就整批作废。
  setInstanceLayers(items) {
    let any = false;
    for (const it of Array.isArray(items) ? items : []) {
      if (it && it.path && Array.isArray(it.layers)) {
        if (this.setInstanceLayersFor(it.path, it.layers)) any = true;
      }
    }
    return any;
  }

  /// 单件版本：地图按路径一个个到货就一个个贴，不必等全图 200 多份计划。
  setInstanceLayersFor(path, layers) {
    const gl = this.gl;
    const pool = this.pool;
    if (!pool || !pool.length) return false;
    const geo = pool.find((g) => g.path === path);
    if (!geo || !geo.buf.uv) return false;
    const token = (geo.layerToken = (geo.layerToken || 0) + 1);
    for (const l of geo.layers || []) {
      if (l.tex) gl.deleteTexture(l.tex);
      if (l.mask) gl.deleteTexture(l.mask);
    }
    geo.layers = [];
    const list = (Array.isArray(layers) ? layers : []).filter(
      (l) => l && l.color && l.color.png && Number(l.faceCount) > 0,
    );
    if (!list.length) return false;
    const jobs = list.map(async (l) => {
        let img;
        try {
          img = await loadImage(l.color.png);
        } catch {
          return null;
        }
        let mask = null;
        if (l.mask && l.mask.png) {
          try {
            mask = await loadImage(l.mask.png);
          } catch {
            mask = null;
          }
        }
        if (this.pool !== pool || geo.layerToken !== token) return null;
        return {
          tex: uploadTexture(gl, img),
          mask: mask ? uploadTexture(gl, mask) : null,
          start: Math.max(0, Number(l.faceStart) || 0) * 3,
          count: Math.max(0, Number(l.faceCount) || 0) * 3,
          blend: l.blend === "add" ? "add" : "opaque",
          slot: l.slot || (l.color && l.color.slot) || "",
          maskSlot: (l.mask && l.mask.slot) || "",
        };
      });
      Promise.allSettled(jobs).then((results) => {
        const ready = results.filter((r) => r.status === "fulfilled" && r.value).map((r) => r.value);
        if (this.pool !== pool || geo.layerToken !== token) {
          for (const l of ready) {
            if (l.tex) gl.deleteTexture(l.tex);
            if (l.mask) gl.deleteTexture(l.mask);
          }
          return;
        }
        geo.layers = ready;
        this.draw();
      });
    return true;
  }

  /// 多实例：朴素但正确——**每个网格 bind 一次几何**，然后对引用它的每个实例
  /// 打一次 uniformMatrix4fv + drawElements（VBO 一条都没为实例建过）。
  ///
  /// 为什么这样够用：瓶颈不在 JS，在 GPU 的**绘制次数**。全图几千实例 = 几千次
  /// drawElements，这属于驱动批处理能吃下的量级，而且"开图看一眼地形"的首次铺开
  /// 几百毫秒可以接受；相机停稳后我们本来就不出帧（见 start 的停帧逻辑）。
  /// 真要撑到十万实例、或要求连续 60fps，才轮到 drawElementsInstanced + 实例属性
  /// 缓冲——那是 WebGL 2 的能力，WebGL 1.0 得拉 ANGLE_instanced_arrays 再分一条
  /// 分支出来。现在不做，因为还没有一个真实数据证明它必要。
  ///
  /// 明确**不做**的事：不为每个实例建 WebGLBuffer，也不每帧 bufferData。
  /// 那不是优化，是把"几千个 GL 对象 + 每帧几千次上传"当成性能来供着。
  ///
  /// 每帧重算的只有 uniform：矩阵在 expandInstances 时就转成列主序、法线矩阵也
  /// 预先归一化好了，所以这里每次只是一次 subarray + 一次 uniform 调用。
  /// 副作用：绘制顺序按网格分组，同一网格的实例连在一起，Z 冲突的相邻物件的
  /// 遮挡关系与半透明（当前没有）无关，纯不透明场景下顺序不影响结果。
  drawInstanced() {
    const gl = this.gl;
    const inst = this.inst;
    gl.uniform1f(this.un.use, 1);
    gl.uniform1f(this.un.useMask, 0);
    gl.uniform1f(this.un.unlit, 0);
    for (let p = 0; p < this.pool.length; p++) {
      const geo = this.pool[p];
      gl.bindBuffer(gl.ARRAY_BUFFER, geo.buf.pos);
      gl.enableVertexAttribArray(this.at.pos);
      gl.vertexAttribPointer(this.at.pos, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, geo.buf.nrm);
      gl.enableVertexAttribArray(this.at.nrm);
      gl.vertexAttribPointer(this.at.nrm, 3, gl.FLOAT, false, 0, 0);
      const layered = geo.layers && geo.layers.length && geo.buf.uv;
      if (layered) {
        gl.bindBuffer(gl.ARRAY_BUFFER, geo.buf.uv);
        gl.enableVertexAttribArray(this.at.uv);
        gl.vertexAttribPointer(this.at.uv, 2, gl.FLOAT, false, 0, 0);
        gl.uniform1f(this.un.useTex, 1);
      } else {
        gl.uniform1f(this.un.useTex, 0);
      }
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, geo.buf.idx);
      for (let i = 0; i < inst.count; i++) {
        if (inst.meshIndex[i] !== p) continue;
        gl.uniformMatrix4fv(this.un.inst, false, inst.model.subarray(i * 16, i * 16 + 16));
        gl.uniformMatrix3fv(this.un.nrm, false, inst.normal.subarray(i * 9, i * 9 + 9));
        if (!layered) {
          gl.drawElements(gl.TRIANGLES, geo.ic, gl.UNSIGNED_SHORT, 0);
          continue;
        }
        // 分层：每层只画自己那段面（与部件/单网格同口径，别把一层的图盖满整件）。
        for (const l of geo.layers) {
          if (!l.count) continue;
          gl.activeTexture(gl.TEXTURE0);
          gl.bindTexture(gl.TEXTURE_2D, l.tex);
          if (l.mask) {
            gl.activeTexture(gl.TEXTURE1);
            gl.bindTexture(gl.TEXTURE_2D, l.mask);
            gl.uniform1f(this.un.useMask, 1);
          } else {
            gl.uniform1f(this.un.useMask, 0);
          }
          if (l.blend === "add") {
            gl.enable(gl.BLEND);
            gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
            gl.depthMask(false);
            gl.enable(gl.POLYGON_OFFSET_FILL);
            gl.polygonOffset(-1, -1);
            gl.uniform1f(this.un.unlit, 1);
          } else {
            gl.disable(gl.BLEND);
            gl.depthMask(true);
            gl.disable(gl.POLYGON_OFFSET_FILL);
            gl.uniform1f(this.un.unlit, 0);
          }
          gl.drawElements(gl.TRIANGLES, l.count, gl.UNSIGNED_SHORT, l.start * 2);
        }
        gl.disable(gl.BLEND);
        gl.depthMask(true);
        gl.disable(gl.POLYGON_OFFSET_FILL);
        gl.uniform1f(this.un.useMask, 0);
        gl.uniform1f(this.un.unlit, 0);
      }
    }
    gl.uniform1f(this.un.useTex, 0);
  }

  /// 整组部件：与多实例同一档朴素——每件 bind 一次几何、drawElements 一次。
  /// 件数是个位数（一只怪的衣服+手套+护腕…），uUseInst 恒 0；每件可各带一套分层
  /// 贴图（动作页 2026-10-29 起也穿图，没计划的件照旧画灰模）。部件共用一副骨架 =
  /// 同一模型空间，不叠加任何件级矩阵，直接画就是拼好的整组。
  drawParts() {
    const gl = this.gl;
    gl.uniform1f(this.un.use, 0);
    for (const p of this.parts) {
      gl.bindBuffer(gl.ARRAY_BUFFER, p.buf.pos);
      gl.enableVertexAttribArray(this.at.pos);
      gl.vertexAttribPointer(this.at.pos, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, p.buf.nrm);
      gl.enableVertexAttribArray(this.at.nrm);
      gl.vertexAttribPointer(this.at.nrm, 3, gl.FLOAT, false, 0, 0);
      const layered = p.layers && p.layers.length && p.buf.uv;
      const single = p.singleReady && p.buf.uv;
      if (layered || single) {
        gl.bindBuffer(gl.ARRAY_BUFFER, p.buf.uv);
        gl.enableVertexAttribArray(this.at.uv);
        gl.vertexAttribPointer(this.at.uv, 2, gl.FLOAT, false, 0, 0);
        gl.uniform1f(this.un.useTex, 1);
      } else {
        gl.uniform1f(this.un.useTex, 0);
        gl.uniform1f(this.un.useMask, 0);
        gl.uniform1f(this.un.unlit, 0);
      }
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, p.buf.idx);
      if (layered) {
        for (const [li, l] of p.layers.entries()) {
          if (!l.count) continue;
          if (p.solo != null && li !== p.solo) continue;
          gl.activeTexture(gl.TEXTURE0);
          gl.bindTexture(gl.TEXTURE_2D, l.tex);
          if (l.mask) {
            gl.activeTexture(gl.TEXTURE1);
            gl.bindTexture(gl.TEXTURE_2D, l.mask);
            gl.uniform1f(this.un.useMask, 1);
          } else {
            gl.uniform1f(this.un.useMask, 0);
          }
          if (l.blend === "add") {
            gl.enable(gl.BLEND);
            gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
            gl.depthMask(false);
            gl.enable(gl.POLYGON_OFFSET_FILL);
            gl.polygonOffset(-1, -1);
            gl.uniform1f(this.un.unlit, 1);
          } else {
            gl.disable(gl.BLEND);
            gl.depthMask(true);
            gl.disable(gl.POLYGON_OFFSET_FILL);
            gl.uniform1f(this.un.unlit, 0);
          }
          gl.drawElements(gl.TRIANGLES, l.count, gl.UNSIGNED_SHORT, l.start * 2);
        }
        gl.disable(gl.BLEND);
        gl.depthMask(true);
        gl.disable(gl.POLYGON_OFFSET_FILL);
        gl.uniform1f(this.un.useMask, 0);
        gl.uniform1f(this.un.unlit, 0);
      } else if (single) {
        gl.disable(gl.BLEND);
        gl.depthMask(true);
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, p.singleTex);
        gl.uniform1f(this.un.useMask, 0);
        gl.uniform1f(this.un.unlit, 0);
        gl.drawElements(gl.TRIANGLES, p.ic, gl.UNSIGNED_SHORT, 0);
      } else {
        gl.drawElements(gl.TRIANGLES, p.ic, gl.UNSIGNED_SHORT, 0);
      }
    }
  }

  /// 点选高亮：把该实例的点选外接盒画成 12 条线；null 清掉。
  setPickBox(index) {
    const gl = this.gl;
    this.pickedBox = null;
    if (index == null || !this.pickBound || !this.pickBound[index]) {
      this.draw();
      return;
    }
    const b = this.pickBound[index].bound;
    const [x0, y0, z0] = b.min;
    const [x1, y1, z1] = b.max;
    const c = [
      [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
      [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1],
    ];
    const edges = [0,1,1,2,2,3,3,0,4,5,5,6,6,7,7,4,0,4,1,5,2,6,3,7];
    const data = new Float32Array(edges.length * 3);
    edges.forEach((ci, k) => data.set(c[ci], k * 3));
    if (!this.pickBuf) this.pickBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.pickBuf);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    this.pickedBox = edges.length;
    this.draw();
  }

  drawPickBox(mv, proj) {
    if (!this.pickedBox || !this.lineProg || !this.pickBuf || this.lineAt < 0) return;
    const gl = this.gl;
    gl.useProgram(this.lineProg);
    gl.uniformMatrix4fv(this.lineUn.mv, false, mv);
    gl.uniformMatrix4fv(this.lineUn.pj, false, proj);
    if (this.lineUn.color) gl.uniform4f(this.lineUn.color, 0.98, 0.55, 0.12, 1.0);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.pickBuf);
    gl.enableVertexAttribArray(this.lineAt);
    gl.vertexAttribPointer(this.lineAt, 3, gl.FLOAT, false, 0, 0);
    gl.disable(gl.DEPTH_TEST);
    gl.drawArrays(gl.LINES, 0, this.pickedBox);
    gl.enable(gl.DEPTH_TEST);
  }

  /// 点选：返回 { index, approximate: true }，没打中返回 null。index 是 instances 数组下标。
  ///
  /// **精度坦白**：这是射线 × 每实例**外接盒**的近似，不是三角形级求交。
  ///   * 会误中：点在物件轮廓内的空隙（两树杈之间、屋檐下）仍算命中；
  ///   * 会被挡：前面的盒子会挡住后面真实存在的物体，报的是前面那个；
  ///   * 单实例若是非等比缩放的斜放物体，外接正方体比物体大得更多，误中更明显。
  /// 对"点物件 → 跳它的 mesh 详情"够用：最坏是点到了隔壁那棵，不是点了空。
  /// 盒子按 t 升序取最近（nearestHit 保证），所以"点到近处那个"这条不会错。
  pickAt(clientX, clientY) {
    if (!this.inst || !this.view || !this.pickBound) return null;
    const rect = this.canvas.getBoundingClientRect();
    const ray = im.pixelRay(clientX, clientY, rect, this.view, FOV, this.aspect || 1);
    return im.nearestHit(ray.origin, ray.dir, this.pickBound);
  }

  dispose() {
    this.stop();
    const gl = this.gl;
    for (const b of Object.values(this.buf)) gl.deleteBuffer(b);
    if (this.boneBuf) gl.deleteBuffer(this.boneBuf);
    if (this.bonePtsBuf) gl.deleteBuffer(this.bonePtsBuf);
    if (this.hlBuf) gl.deleteBuffer(this.hlBuf);
    if (this.hlPtsBuf) gl.deleteBuffer(this.hlPtsBuf);
    this.unloadPool();
    this.unloadParts();
    gl.deleteProgram(this.prog);
    if (this.lineProg) gl.deleteProgram(this.lineProg);
    this.mesh = null;
    this.inst = null;
    this.pickBound = null;
  }
}

const mat4 = {
  identity: () => new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]),
  translate: (x, y, z) => new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]),
  rotateX: (r) => { const c = Math.cos(r), s = Math.sin(r); return new Float32Array([1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 0, 0, 1]); },
  rotateY: (r) => { const c = Math.cos(r), s = Math.sin(r); return new Float32Array([c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]); },
  mul(a, b) {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++) {
      for (let r = 0; r < 4; r++) {
        o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
      }
    }
    return o;
  },
  perspective(fov, aspect, near, far) {
    const f = 1 / Math.tan(fov / 2), nf = 1 / (near - far);
    return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]);
  },
};
