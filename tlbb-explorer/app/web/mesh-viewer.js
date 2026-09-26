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
  gl_Position = uProjection * mv;
}`;

// 双面半兰伯特：绕序未知时剔除会整块黑，故只靠法线朝向翻转补光。
const FS = `
precision mediump float;
varying vec3 vNormal;
varying vec3 vView;
void main() {
  vec3 n = normalize(vNormal);
  vec3 l = normalize(vec3(0.35, 0.75, 0.6));
  float d = dot(n, l) * 0.5 + 0.5;
  float rim = pow(1.0 - abs(dot(normalize(-vView), n)), 2.0) * 0.25;
  vec3 col = vec3(0.62, 0.65, 0.69) * (0.32 + 0.68 * d) + rim;
  gl_FragColor = vec4(col, 1.0);
}`;

// 视场角。抽成常量是因为 draw() 用它投影、pickAt 用它反投影——
// 两处各写一个数字，改了其中一处就会出现"看着点中了，其实偏一条街"。
const FOV = Math.PI / 4.5;

function compile(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    throw new Error("着色器编译失败：" + gl.getShaderInfoLog(sh));
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

  const buf = { pos: gl.createBuffer(), nrm: gl.createBuffer(), idx: gl.createBuffer() };
  gl.bindBuffer(gl.ARRAY_BUFFER, buf.pos);
  gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
  gl.bindBuffer(gl.ARRAY_BUFFER, buf.nrm);
  gl.bufferData(gl.ARRAY_BUFFER, normals, gl.STATIC_DRAW);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, buf.idx);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.STATIC_DRAW);

  return { buf, positions, normals, indices, ic: layout.indexCount, vertexCount: vc };
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

export class MeshViewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext("webgl", { antialias: true });
    if (!this.gl) throw new Error("这台机器开不了 WebGL，看不到 3D 预览");

    const gl = this.gl;
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, VS));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      throw new Error("着色器链接失败：" + gl.getProgramInfoLog(prog));
    }
    this.prog = prog;
    this.at = { pos: gl.getAttribLocation(prog, "aPosition"), nrm: gl.getAttribLocation(prog, "aNormal") };
    this.un = {
      mv: gl.getUniformLocation(prog, "uModelView"),
      pj: gl.getUniformLocation(prog, "uProjection"),
      inst: gl.getUniformLocation(prog, "uInstance"),
      nrm: gl.getUniformLocation(prog, "uNormalMat"),
      use: gl.getUniformLocation(prog, "uUseInst"),
    };
    // 老路径用的三个专用缓冲：单网格时不动，行为和以前一样。
    this.buf = { pos: gl.createBuffer(), nrm: gl.createBuffer(), idx: gl.createBuffer() };

    // 多实例路径的几何池：每个**不同网格**一份缓冲，在 loadInstances 里上传一次。
    // 绝不每帧 bufferData，也绝不为每个实例建一个 buffer——后者在几千实例下是
    // 几千个 GL 对象 + 每帧几千次 bind，纯属自我惩罚。
    this.pool = [];
    this.inst = null;
    this.pickBound = null;

    this.home = { dist: 3, rx: -0.25, ry: 0.6 };
    this.cam = { ...this.home, trx: this.home.rx, try: this.home.ry, tdist: this.home.dist };
    this.drag = null;
    this.raf = 0;
    this.mesh = null;
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
      c.parentElement.classList.remove("dragging");
      this.start(); // 松手后还要把惯性补完
    };
    c.addEventListener("pointerup", release);
    c.addEventListener("pointercancel", release);
    c.addEventListener("wheel", (e) => {
      if (!this.mesh && !this.inst) return; // 还没加载模型时让页面正常滚
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
      // 上下文没了，缓冲和 program 都成了废引用：多实例路径的状态必须一并清掉，
      // 不然"buffer 还在、其实早就没了"会一路带进下一次 draw。
      this.mesh = null;
      this.inst = null;
      this.pool = [];
      this.pickBound = null;
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

  load(data) {
    const gl = this.gl;
    // 长度与偏移由 lib/meshLayout.js 统一校验（有 node --test 盯着）：
    // 声明和实际字节数不符时必须拒绝，绝不能把错数据画得像个模型。
    // 解包只走 uploadMesh 一处：单网格和多实例各写一份解包，迟早有一边跑偏。
    const geo = uploadMesh(gl, data);
    // uploadMesh 用的是临时缓冲，这里把它换到老路径那三个专用缓冲上，
    // 然后立刻回收临时的那一份——不然每 load 一次就漏三个 buffer。
    const tmp = geo.buf;
    geo.buf = this.buf;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.pos);
    gl.bufferData(gl.ARRAY_BUFFER, geo.positions, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf.nrm);
    gl.bufferData(gl.ARRAY_BUFFER, geo.normals, gl.STATIC_DRAW);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.buf.idx);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, geo.indices, gl.STATIC_DRAW);
    for (const b of [tmp.pos, tmp.nrm, tmp.idx]) gl.deleteBuffer(b);

    this.unloadPool(); // 从多实例切回单网格：地图的几何池该收掉了
    this.mesh = viewOf(geo, data);
    this.inst = null;
    this.pickBound = null;
    // 单网格的"家"就是它自己的局部盒（跟扩展前一样）。这里不走实例那套
    // 世界包围盒：实例数为 1 且矩阵是单位阵，结果完全等价，多绕一圈只会
    // 让人以为单网格也支持变换。
    this.applyFrame({ center: this.mesh.center, size: this.mesh.size });
    this.trackAllocation();
    this.syncViewport();
    this.draw(); // 先画定一帧：窗口没聚焦时 rAF 会被挂起，否则首帧要等很久
  }

  /// 几何池整体换新/清空都从这里走，保证三个缓冲一个不漏。
  unloadPool() {
    const gl = this.gl;
    for (const p of this.pool) for (const b of [p.buf.pos, p.buf.nrm, p.buf.idx]) gl.deleteBuffer(b);
    this.pool = [];
  }

  /// load / loadInstances 都在**画第一帧之前**调一次：此刻还没有任何需要保护的
  /// 画面，设置 uUseInst 不会被谁挡住，渲染态也就不会在两条路径之间串。
  trackAllocation() {
    this.useInstanced(Boolean(this.inst));
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
      for (const p of fresh) for (const b of [p.buf.pos, p.buf.nrm, p.buf.idx]) gl.deleteBuffer(b);
      throw e;
    }
    this.unloadPool();
    this.pool = fresh;

    // 实例表：矩阵预先转置 + 预先推法线矩阵，绘制时只剩一次 uniformMatrix 调用。
    // 注意 instances 里的 meshIndex 指的是**原** meshes 顺序，要映射到池下标。
    this.inst = im.expandInstances(instances, meshes.length);
    for (let i = 0; i < this.inst.count; i++) this.inst.meshIndex[i] = toUnique[this.inst.meshIndex[i]];

    this.bounds = instancedBounds(fresh, this.inst);
    this.pickBound = instancedPickBounds(fresh, this.inst);
    this.mesh = null;
    this.applyFrame(this.bounds);
    this.trackAllocation();
    this.syncViewport();
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
    gl.clearColor(0.055, 0.067, 0.078, 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!this.mesh && !this.inst) return false;
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
    gl.useProgram(this.prog);
    gl.uniformMatrix4fv(this.un.pj, false, mat4.perspective(FOV, aspect, this.near, this.far));
    gl.uniformMatrix4fv(this.un.mv, false, mv);

    if (this.inst) this.drawInstanced();
    else this.drawSingle();
    return !settled;
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
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.buf.idx);
    gl.drawElements(gl.TRIANGLES, this.mesh.ic, gl.UNSIGNED_SHORT, 0);
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
    for (let p = 0; p < this.pool.length; p++) {
      const geo = this.pool[p];
      gl.bindBuffer(gl.ARRAY_BUFFER, geo.buf.pos);
      gl.enableVertexAttribArray(this.at.pos);
      gl.vertexAttribPointer(this.at.pos, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, geo.buf.nrm);
      gl.enableVertexAttribArray(this.at.nrm);
      gl.vertexAttribPointer(this.at.nrm, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, geo.buf.idx);
      for (let i = 0; i < inst.count; i++) {
        if (inst.meshIndex[i] !== p) continue;
        gl.uniformMatrix4fv(this.un.inst, false, inst.model.subarray(i * 16, i * 16 + 16));
        gl.uniformMatrix3fv(this.un.nrm, false, inst.normal.subarray(i * 9, i * 9 + 9));
        gl.drawElements(gl.TRIANGLES, geo.ic, gl.UNSIGNED_SHORT, 0);
      }
    }
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
    this.unloadPool();
    gl.deleteProgram(this.prog);
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
