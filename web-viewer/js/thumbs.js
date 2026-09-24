// 缩略图：把立体文件真的渲染一遍取图，不是占位图标。
// 一台离屏渲染器共用，队列限流，画过的缓存住。

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const SIZE = 256;
const MAX_KEEP = 900;
const cache = new Map();
const pending = new Map();
let queue = [];
let busy = 0;
const CONCURRENCY = 3;

let renderer = null;
function gl() {
  if (!renderer) {
    const c = document.createElement("canvas");
    c.width = c.height = SIZE;
    renderer = new THREE.WebGLRenderer({ canvas: c, antialias: true, preserveDrawingBuffer: true });
    renderer.setClearColor(0x0a0e12, 1);
  }
  return renderer;
}

function frame(camera, box) {
  const size = Math.max(box.getSize(new THREE.Vector3()).length(), 1e-3);
  const center = box.getCenter(new THREE.Vector3());
  camera.position.set(center.x + size * 0.75, center.y + size * 0.42, center.z + size * 0.95);
  camera.near = Math.max(size * 0.005, 0.01);
  camera.far = size * 20;
  camera.lookAt(center);
  return { center, size };
}

async function renderOne(url) {
  const r = gl();
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xe6edf4, 0x1b232c, 1.15));
  const key = new THREE.DirectionalLight(0xffffff, 1.5);
  key.position.set(1.2, 2.2, 1.6);
  scene.add(key);
  const cam = new THREE.PerspectiveCamera(38, 1, 0.01, 100);
  r.setSize(SIZE, SIZE, false);
  try {
    const gltf = await new GLTFLoader().loadAsync(url);
    scene.add(gltf.scene);
    const box = new THREE.Box3().setFromObject(gltf.scene);
    if (box.isEmpty()) throw new Error("空包围盒");
    frame(cam, box);
    r.render(scene, cam);
    const dataUrl = r.domElement.toDataURL("image/jpeg", 0.72);
    return dataUrl;
  } finally {
    scene.traverse((o) => {
      if (o.isMesh) {
        o.geometry?.dispose?.();
        for (const m of [].concat(o.material || [])) m?.dispose?.();
      }
    });
  }
}

export function cached(id) {
  return cache.get(id);
}

export function thumb(asset) {
  if (cache.has(asset.id)) return Promise.resolve(cache.get(asset.id));
  if (pending.has(asset.id)) return pending.get(asset.id);
  const p = new Promise((res) => {
    queue.push({ asset, res });
    pump();
  });
  pending.set(asset.id, p);
  return p;
}

function pump() {
  while (busy < CONCURRENCY && queue.length) {
    const job = queue.shift();
    const a = job.asset;
    busy++;
    renderOne("./model/" + a.glb)
      .then((url) => {
        cache.set(a.id, url);
        if (cache.size > MAX_KEEP) cache.delete(cache.keys().next().value);
        job.res({ url, error: "" });
      })
      .catch((e) => job.res({ url: "", error: String(e && e.message ? e.message : e) }))
      .finally(() => {
        pending.delete(a.id);
        busy--;
        pump();
      });
  }
}

export function depth() {
  return queue.length + busy;
}
