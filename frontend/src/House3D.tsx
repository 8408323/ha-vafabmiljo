// The house and its bins in 3D (three.js): drag to orbit, scroll or pinch to zoom; it turns slowly by itself
// until touched. Same layout and bin sizes as the isometric SVG (House.tsx), which stays the fallback without
// WebGL and is shown while this chunk loads. Scene units are metres; the SVG's (x, y, z) - x along the road,
// y towards it, z up - is three's (x, z, y).
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { K, SceneBin, spec } from "./House";

type Props = { bins: SceneBin[]; truck: boolean; dark: boolean; accent: string; onFail: () => void };

const CURB = 6.8;
const REDUCED = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
// the camera survives a rebuild (new data, theme switch), so a view someone turned to isn't reset
let savedView: { pos: THREE.Vector3; target: THREE.Vector3 } | null = null;

export default function House3D({ bins, truck, dark, accent, onFail }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const key = JSON.stringify([bins.map((b) => [b.type, b.next]), truck, dark, accent]);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      onFail();
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = dark ? 0.95 : 1.05;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    // the far ground fades into the card instead of ending at an edge
    scene.fog = new THREE.Fog(dark ? "#131f19" : "#ffffff", 26, 58);
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 200);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = false;
    controls.minDistance = 9;
    controls.maxDistance = 42;
    controls.maxPolarAngle = Math.PI * 0.46;  // never under the ground
    controls.autoRotate = !REDUCED;
    controls.autoRotateSpeed = 0.55;
    if (savedView) {
      camera.position.copy(savedView.pos);
      controls.target.copy(savedView.target);
    } else {
      camera.position.set(9.5, 6.6, 15.2);
      controls.target.set(0.9, 0.9, 4.6);
    }
    // stop turning while someone looks around; carry on after a while
    let idle: number | undefined;
    controls.addEventListener("start", () => { controls.autoRotate = false; window.clearTimeout(idle); });
    controls.addEventListener("end", () => {
      window.clearTimeout(idle);
      if (!REDUCED) idle = window.setTimeout(() => { controls.autoRotate = true; }, 9000);
    });

    const pal = dark
      ? { grass: "#1f3a2a", grass2: "#18301f", plot: "#264733", path: "#5b6168", road: "#1d2026", curb: "#7b828c", wall: "#e9edf2", roof: "#262a31", trunk: "#5a4030", leaf: "#2f8f5a", leaf2: "#3aa86a" }
      : { grass: "#cfe5c0", grass2: "#bcd9aa", plot: "#b7d7a2", path: "#d9d3c7", road: "#3a3f48", curb: "#c9ccd2", wall: "#fbfcfd", roof: "#30343c", trunk: "#7a5636", leaf: "#3f9e5f", leaf2: "#52b874" };
    const mat = (color: string, extra: THREE.MeshStandardMaterialParameters = {}) =>
      new THREE.MeshStandardMaterial({ color, roughness: 0.82, metalness: 0.02, ...extra });
    const add = (mesh: THREE.Mesh, cast = true, receive = true) => {
      mesh.castShadow = cast;
      mesh.receiveShadow = receive;
      scene.add(mesh);
      return mesh;
    };
    // a box from SVG coordinates: x0..x1 along the road, y0..y1 towards it, z0..z1 up
    const box = (x0: number, x1: number, y0: number, y1: number, z0: number, z1: number, m: THREE.Material, parent?: THREE.Object3D) => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(x1 - x0, z1 - z0, y1 - y0), m);
      mesh.position.set((x0 + x1) / 2, (z0 + z1) / 2, (y0 + y1) / 2);
      mesh.castShadow = mesh.receiveShadow = true;
      (parent ?? scene).add(mesh);
      return mesh;
    };

    // light: sky/ground fill and a low sun from the front-left, casting soft shadows
    scene.add(new THREE.HemisphereLight(dark ? "#9fb7c9" : "#ffffff", dark ? "#2a3f32" : "#9fbf8a", dark ? 0.95 : 0.85));
    const sun = new THREE.DirectionalLight(dark ? "#cfe0ff" : "#fff4e0", dark ? 1.6 : 2.3);
    sun.position.set(-9, 16, 14);
    sun.target.position.set(1.5, 0, 3.5);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -16, right: 16, top: 16, bottom: -16, near: 1, far: 60 });
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.02;
    scene.add(sun, sun.target);

    // ground: a round lawn, the plot, the path to the street, the street with its curb and dashed centre line
    const lawn = add(new THREE.Mesh(new THREE.CircleGeometry(80, 64), mat(pal.grass2)), false);
    lawn.rotation.x = -Math.PI / 2;
    lawn.position.set(1.5, -0.02, 3.5);
    box(-4.8, 7.6, -0.5, 6.9, -0.02, 0.02, mat(pal.plot));
    box(3.5, 4.5, 3.5, 6.9, 0.02, 0.05, mat(pal.path));
    box(-14, 17, 6.95, 8.65, -0.02, 0.01, mat(pal.road, { roughness: 0.95 }));
    box(-14, 17, 6.85, 6.97, 0, 0.1, mat(pal.curb));
    for (let x = -13; x < 17; x += 2.2) box(x, x + 1.1, 7.75, 7.85, 0.01, 0.015, mat("#e9edf2", { roughness: 0.6 }));

    // house: walls, gables, a pitched roof with a small overhang, windows, a door and a chimney
    const wall = mat(pal.wall, { roughness: 0.7 });
    box(0, 6, 0, 3.5, 0, 2.6, wall);
    const gable = new THREE.Shape([new THREE.Vector2(0, 2.6), new THREE.Vector2(3.5, 2.6), new THREE.Vector2(1.75, 4.25)]);
    for (const x of [0, 5.99]) {
      const g = add(new THREE.Mesh(new THREE.ExtrudeGeometry(gable, { depth: 0.01, bevelEnabled: false }), wall));
      g.rotation.y = -Math.PI / 2;
      g.position.set(x + 0.01, 0, 0);
    }
    const roofMat = mat(pal.roof, { roughness: 0.6 });
    const slope = Math.hypot(2.15, 1.85);
    for (const side of [1, -1]) {
      const r = add(new THREE.Mesh(new THREE.BoxGeometry(6.6, 0.12, slope), roofMat));
      r.rotation.x = side * Math.atan2(1.85, 2.15);
      r.position.set(3, 3.38, 1.75 + (side * 2.15) / 2);
    }
    box(-0.3, 6.3, 1.68, 1.82, 4.22, 4.36, mat("#1d2027"));
    box(4.3, 4.85, 0.9, 1.45, 3.1, 4.6, mat(dark ? "#6b4a3a" : "#9c5b45"));
    const glass = mat(dark ? "#ffd98a" : "#9fd3f2", dark
      ? { emissive: new THREE.Color("#ffb54a"), emissiveIntensity: 0.9, roughness: 0.3 }
      : { roughness: 0.15, metalness: 0.2 });
    const frameMat = mat("#ffffff", { roughness: 0.5 });
    for (const [a, b] of [[0.5, 1.4], [1.9, 2.8], [5, 5.6]]) {
      box(a - 0.06, b + 0.06, 3.5, 3.56, 1.14, 2.16, frameMat);
      box(a, b, 3.5, 3.6, 1.2, 2.1, glass);
    }
    for (const y0 of [0.8, 2.1]) {
      box(6, 6.06, y0 - 0.06, y0 + 0.76, 1.14, 2.16, frameMat);
      box(6, 6.1, y0, y0 + 0.7, 1.2, 2.1, glass);
    }
    // the back and the far gable, so the house looks lived-in from every side
    for (const [a, b] of [[0.8, 1.7], [2.6, 3.5], [4.6, 5.4]]) {
      box(a - 0.06, b + 0.06, -0.06, 0, 1.14, 2.16, frameMat);
      box(a, b, -0.1, 0, 1.2, 2.1, glass);
    }
    box(-0.06, 0, 1.34, 2.16, 1.14, 2.16, frameMat);
    box(-0.1, 0, 1.4, 2.1, 1.2, 2.1, glass);
    box(-0.06, 0, 1.5, 2.0, 2.95, 3.45, frameMat);
    box(-0.1, 0, 1.55, 1.95, 3.0, 3.4, glass);
    box(3.6, 4.4, 3.5, 3.58, 0, 1.9, mat("#8a6a4a", { roughness: 0.6 }));
    box(3.95, 4.05, 3.58, 3.64, 0.9, 1.0, mat("#d9b45a", { metalness: 0.6, roughness: 0.3 }));
    box(3.4, 4.6, 3.5, 4.2, 0, 0.08, mat(pal.path));

    // trees: a trunk and two stacked crowns
    const tree = (x: number, y: number, s = 1) => {
      const t = add(new THREE.Mesh(new THREE.CylinderGeometry(0.12 * s, 0.16 * s, 1.4 * s, 8), mat(pal.trunk)));
      t.position.set(x, 0.7 * s, y);
      for (const [r, h, c] of [[0.95, 1.85, pal.leaf], [0.7, 2.55, pal.leaf2]] as const) {
        const crown = add(new THREE.Mesh(new THREE.IcosahedronGeometry(r * s, 1), mat(c, { flatShading: true })));
        crown.position.set(x, h * s, y);
      }
    };
    tree(-3.6, 1.6); tree(-2.4, 0.2, 0.85); tree(7.0, 1.2, 1.1); tree(-6.5, 3.8, 1.2); tree(10, 2.5, 0.95);

    // bins in a row at the curb, as wide and deep as their real counterparts; the next pickup's glow
    const glows: THREE.Mesh[] = [];
    let x = -4.3;
    for (const b of bins) {
      const s = spec(b.type), w = s.w * K, d = s.d * K, h = s.h * K;
      const y = CURB - d;
      const g = new THREE.Group();
      g.position.set(x + w / 2, 0, y + d / 2);
      const body = new THREE.Mesh(new RoundedBoxGeometry(w, h * 0.92, d, 3, 0.05), mat(s.body, { roughness: 0.55 }));
      body.position.y = (h * 0.92) / 2 + 0.06;
      body.castShadow = body.receiveShadow = true;
      g.add(body);
      const lids = s.split ? [[-w / 4, w / 2 - 0.02], [w / 4, w / 2 - 0.02]] : [[0, w + 0.04]];
      for (const [lx, lw] of lids) {
        const lid = new THREE.Mesh(new RoundedBoxGeometry(lw, 0.07, d + 0.06, 2, 0.025), mat(s.lid, { roughness: 0.45 }));
        lid.position.set(lx, h * 0.92 + 0.09, 0.02);
        lid.castShadow = true;
        g.add(lid);
      }
      if (s.split) {  // the black SULO's purple marker on the plastic half
        const tag = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.01, 0.12), mat("#8e44ad"));
        tag.position.set(-w / 4, h * 0.92 + 0.13, 0.05);
        g.add(tag);
      }
      const handle = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, w * 0.8, 8), mat("#2a2d33"));
      handle.rotation.z = Math.PI / 2;
      handle.position.set(0, h * 0.86, -d / 2 - 0.05);
      g.add(handle);
      for (const wx of [-w / 2 + 0.06, w / 2 - 0.06]) {
        const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.1, 0.06, 16), mat("#15171b"));
        wheel.rotation.z = Math.PI / 2;
        wheel.position.set(wx, 0.1, -d / 2 + 0.08);
        g.add(wheel);
      }
      if (b.next) {
        const ring = new THREE.Mesh(new THREE.RingGeometry(Math.max(w, d) * 0.72, Math.max(w, d) * 1.05, 48),
          new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0.6, side: THREE.DoubleSide, depthWrite: false }));
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.04;
        g.add(ring);
        glows.push(ring);
      }
      scene.add(g);
      x += w + 0.9;
    }

    // the refuse truck on pickup day, parked past the bins it has just emptied
    let truckGroup: THREE.Group | null = null;
    if (truck) {
      const t = new THREE.Group();
      const X = 2.2, y0 = 7.05, y1 = 8.35;
      box(X + 0.1, X + 5.2, y0 + 0.1, y1 - 0.1, 0.32, 0.55, mat("#2b2f37"), t);
      const body = new THREE.Mesh(new RoundedBoxGeometry(3.5, 1.8, y1 - y0, 3, 0.12), mat("#2f9e5b", { roughness: 0.45 }));
      body.position.set(X + 1.75, 1.45, (y0 + y1) / 2);
      body.castShadow = true;
      t.add(body);
      box(X, X + 3.5, y1 - 0.01, y1 + 0.03, 0.55, 0.8, mat("#e9eef5"), t);
      // the side text, drawn on a canvas
      const c = document.createElement("canvas");
      c.width = 512; c.height = 128;
      const g2 = c.getContext("2d");
      if (g2) {
        g2.fillStyle = "#38b26a"; g2.fillRect(0, 0, 512, 128);
        g2.fillStyle = "#ffffff"; g2.font = "bold 64px sans-serif"; g2.textAlign = "center"; g2.textBaseline = "middle";
        g2.fillText("VafabMiljö", 256, 68);
      }
      const label = new THREE.Mesh(new THREE.PlaneGeometry(3.1, 0.78), new THREE.MeshStandardMaterial({ map: new THREE.CanvasTexture(c), roughness: 0.6 }));
      label.position.set(X + 1.75, 1.5, y1 + 0.02);
      t.add(label);
      const cab = new THREE.Mesh(new RoundedBoxGeometry(1.4, 1.45, y1 - y0, 3, 0.12), mat("#eef2f7", { roughness: 0.4 }));
      cab.position.set(X + 4.3, 1.27, (y0 + y1) / 2);
      cab.castShadow = true;
      t.add(cab);
      const win = mat("#9fd3f2", { roughness: 0.1, metalness: 0.3 });
      box(X + 5.0, X + 5.03, y0 + 0.15, y1 - 0.15, 1.2, 1.85, win, t);
      box(X + 3.75, X + 4.6, y1, y1 + 0.03, 1.25, 1.85, win, t);
      box(X + 3.75, X + 4.6, y0 - 0.03, y0, 1.25, 1.85, win, t);
      box(X + 5.0, X + 5.03, y1 - 0.35, y1 - 0.12, 0.65, 0.8, mat("#fff3c4", { emissive: new THREE.Color("#fff0b0"), emissiveIntensity: 0.6 }), t);
      const beacon = box(X + 0.6, X + 1.0, y0 + 0.4, y0 + 0.8, 2.35, 2.5, mat("#f5b301", { emissive: new THREE.Color("#f5a000"), emissiveIntensity: 0.8 }), t);
      box(X + 4.0, X + 4.15, y0 + 0.05, y0 + 0.2, 2.0, 2.75, mat("#6b7484", { metalness: 0.5, roughness: 0.4 }), t);
      for (const wx of [X + 0.7, X + 1.7, X + 4.3]) {
        for (const wy of [y0, y1]) {
          const tyre = new THREE.Mesh(new THREE.CylinderGeometry(0.38, 0.38, 0.28, 20), mat("#15171b", { roughness: 0.9 }));
          tyre.rotation.x = Math.PI / 2;
          tyre.position.set(wx, 0.38, wy + (wy === y0 ? 0.1 : -0.1));
          tyre.castShadow = true;
          t.add(tyre);
          const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.3, 12), mat("#9aa4b2", { metalness: 0.6, roughness: 0.3 }));
          hub.rotation.x = Math.PI / 2;
          hub.position.copy(tyre.position);
          t.add(hub);
        }
      }
      t.userData.beacon = beacon;
      scene.add(t);
      truckGroup = t;
    }

    // size to the card; render only while visible
    const resize = () => {
      const w = el.clientWidth || 600, h = el.clientHeight || 380;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    let visible = true;
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; });
    io.observe(el);

    const start = performance.now();
    let frame = 0;
    const loop = (now: number) => {
      frame = requestAnimationFrame(loop);
      if (!visible || document.hidden) return;
      const t = (now - start) / 1000;
      for (const g of glows) (g.material as THREE.MeshBasicMaterial).opacity = REDUCED ? 0.55 : 0.35 + 0.3 * (0.5 + 0.5 * Math.sin(t * 3));
      if (truckGroup) {
        // drives in from the left on load, then the beacon blinks
        const p = REDUCED ? 1 : Math.min(1, t / 1.6);
        truckGroup.position.x = -16 * (1 - p) ** 3;
        const beacon = truckGroup.userData.beacon as THREE.Mesh;
        (beacon.material as THREE.MeshStandardMaterial).emissiveIntensity = REDUCED ? 0.8 : 0.3 + 0.9 * (Math.sin(t * 8) > 0 ? 1 : 0);
      }
      controls.update();
      renderer.render(scene, camera);
    };
    frame = requestAnimationFrame(loop);

    return () => {
      savedView = { pos: camera.position.clone(), target: controls.target.clone() };
      cancelAnimationFrame(frame);
      window.clearTimeout(idle);
      ro.disconnect();
      io.disconnect();
      controls.dispose();
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        if (m.geometry) m.geometry.dispose();
        const mats = Array.isArray(m.material) ? m.material : m.material ? [m.material] : [];
        for (const x of mats) { (x as THREE.MeshStandardMaterial).map?.dispose(); x.dispose(); }
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [key]);

  return <div ref={host} className="scene3d" role="img" aria-label="3D: house with waste bins (drag to rotate)" />;
}
