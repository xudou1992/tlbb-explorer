// 详情页的立体窗口：转、缩、双击复位，按材质槽单独显隐。
// 不剔背面（这个格式的绕序还没核实），灯光用半球光 + 一盏主光。

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export class DetailViewer {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setClearColor(0x0b0f13, 1);
    this.scene = new THREE.Scene();
    this.scene.add(new THREE.HemisphereLight(0xe6edf4, 0x1b232c, 1.15));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1.4, 2.4, 1.8);
    this.scene.add(key);
    const fill = new THREE.DirectionalLight(0x9fb6cc, 0.6);
    fill.position.set(-1.6, 0.8, -1.4);
    this.scene.add(fill);
    this.cam = new THREE.PerspectiveCamera(42, 1, 0.01, 200);
    this.controls = new OrbitControls(this.cam, canvas);
    this.controls.enableDamping = false;
    this.home = null;
    this.group = null;
    this.parts = [];
    this.seq = 0;
    this.raf = 0;
    canvas.addEventListener("dblclick", () => this.reset());
    canvas.addEventListener("pointerdown", () => canvas.classList.add("drag"));
    window.addEventListener("pointerup", () => canvas.classList.remove("drag"));
    window.addEventListener("resize", () => this.resize());
  }

  resize() {
    const r = this.canvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.renderer.setSize(Math.max(1, r.width), Math.max(1, r.height), false);
    this.renderer.setPixelRatio(dpr);
    this.cam.aspect = Math.max(0.2, r.width / Math.max(1, r.height));
    this.cam.updateProjectionMatrix();
  }

  clear() {
    if (!this.group) return;
    this.group.traverse((o) => {
      if (o.isMesh) {
        o.geometry?.dispose?.();
        for (const m of [].concat(o.material || [])) m?.dispose?.();
      }
    });
    this.scene.remove(this.group);
    this.group = null;
    this.parts = [];
  }

  async load(url) {
    const my = ++this.seq;
    const gltf = await new GLTFLoader().loadAsync(url);
    if (my !== this.seq) return { dropped: true, parts: [] };
    this.clear();
    this.group = gltf.scene;
    this.scene.add(this.group);
    const box = new THREE.Box3().setFromObject(this.group);
    const size = Math.max(box.getSize(new THREE.Vector3()).length(), 1e-3);
    const center = box.getCenter(new THREE.Vector3());
    this.parts = [];
    this.group.traverse((o) => {
      if (o.isMesh) this.parts.push(o);
    });
    this.cam.position
      .copy(center)
      .add(new THREE.Vector3(size * 0.72, size * 0.38, size * 0.98));
    this.cam.near = Math.max(size * 0.004, 0.01);
    this.cam.far = size * 24;
    this.controls.target.copy(center);
    this.controls.update();
    this.home = { pos: this.cam.position.clone(), target: center.clone() };
    this.resize();
    // 先同步画一帧：页面没聚焦时 rAF 会被挂起，否则首帧要等很久。
    this.renderer.render(this.scene, this.cam);
    this.start();
    return { dropped: false, parts: this.parts, size, center };
  }

  reset() {
    if (!this.home) return;
    this.cam.position.copy(this.home.pos);
    this.controls.target.copy(this.home.target);
    this.start();
  }

  setVisible(i, on) {
    const o = this.parts[i];
    if (o) {
      o.visible = on;
      this.start();
    }
  }

  start() {
    if (this.raf) return;
    this.renderer.render(this.scene, this.cam); // 隐藏页 rAF 会挂起，先落一帧
    const frame = () => {
      this.controls.update();
      this.renderer.render(this.scene, this.cam);
      this.raf = requestAnimationFrame(frame);
    };
    this.raf = requestAnimationFrame(frame);
  }

  stop() {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
  }
}
