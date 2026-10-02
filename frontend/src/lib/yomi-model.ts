import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";

type Point = [number, number, number];
type Section = [number, number, number, number];
type Expression = "idle" | "happy" | "read" | "blink";
export type MascotAction = "wave" | "happy" | "read";

// A locally generated fan interpretation of Alya, with no remote model or texture requests.
export function createYomiModel() {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  const textures = new Set<THREE.Texture>();
  const gradient = new THREE.DataTexture(new Uint8Array([180, 220, 255, 255]), 4, 1, THREE.RedFormat);
  gradient.minFilter = gradient.magFilter = THREE.NearestFilter;
  gradient.needsUpdate = true;
  textures.add(gradient);

  function material(color: string) {
    const value = new THREE.MeshStandardMaterial({ color, roughness: 0.84 });
    materials.add(value);
    return value;
  }
  const skin = material("#ffebde");
  const silver = material("#ddd9e7");
  const pearl = material("#f7f1f2");
  const silverShade = material("#b7b1ca");
  const cloth = material("#f5f0e7");
  const seam = material("#d5c9cc");
  const navy = material("#2b3d61");
  const crimson = material("#b63151");
  const ribbonLight = material("#e45870");
  const bookCover = material("#394762");
  const gold = material("#dfbd80");

  const sphere = new THREE.SphereGeometry(1, 24, 16);
  const rounded = new RoundedBoxGeometry(1, 1, 1, 3, 0.09);
  function mesh(parent: THREE.Object3D, geometry: THREE.BufferGeometry, surface: THREE.Material | THREE.Material[], position: Point = [0, 0, 0], scale: Point = [1, 1, 1]) {
    geometries.add(geometry);
    const value = new THREE.Mesh(geometry, surface);
    value.position.set(...position);
    value.scale.set(...scale);
    value.castShadow = true;
    // Soft studio illumination keeps facial marks readable without hair shadow artifacts.
    value.receiveShadow = false;
    parent.add(value);
    return value;
  }
  const ball = (parent: THREE.Object3D, surface: THREE.Material, position: Point, scale: Point) => mesh(parent, sphere, surface, position, scale);
  const box = (parent: THREE.Object3D, surface: THREE.Material, position: Point, scale: Point) => mesh(parent, rounded, surface, position, scale);
  function group(parent: THREE.Object3D, position: Point = [0, 0, 0]) {
    const value = new THREE.Group();
    value.position.set(...position);
    parent.add(value);
    return value;
  }
  function tube(parent: THREE.Object3D, surface: THREE.Material, points: Point[], radius: number) {
    const curve = new THREE.CatmullRomCurve3(points.map(p => new THREE.Vector3(...p)));
    return mesh(parent, new THREE.TubeGeometry(curve, 32, radius, 8, false), surface);
  }

  function sectionAt(sections: Section[], t: number) {
    const index = Math.min(Math.floor(t * (sections.length - 1)), sections.length - 2);
    const f = THREE.MathUtils.smoothstep(t * (sections.length - 1) - index, 0, 1);
    return sections[index].map((value, axis) => THREE.MathUtils.lerp(value, sections[index + 1][axis], f));
  }
  function surface(sections: Section[], face = false) {
    const vertices: number[] = [], uv: number[] = [], indices: number[] = [];
    const rows = (sections.length - 1) * 5, columns = 64;
    const geometry = new THREE.BufferGeometry();
    for (let row = 0; row <= rows; row++) {
      const [y, rx, rz, centerZ] = sectionAt(sections, row / rows);
      for (let col = 0; col <= columns; col++) {
        const angle = col / columns * Math.PI * 2;
        const cosine = Math.cos(angle);
        const x = rx * Math.sin(angle);
        const z = centerZ + rz * (face && cosine > 0 ? Math.pow(cosine, 0.45) : cosine);
        vertices.push(x, y, z);
        uv.push((x + 0.8) / 1.6, (y + 0.9) / 2);
      }
    }
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < columns; col++) {
        const a = row * (columns + 1) + col, b = a + columns + 1;
        geometry.addGroup(indices.length, 6, face && Math.cos((col + 0.5) / columns * Math.PI * 2) > 0 ? 1 : 0);
        indices.push(a, a + 1, b, a + 1, b + 1, b);
      }
    }
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
    geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();
    // Material groups only need separate runs for the front and back of the face.
    const groups = geometry.groups.slice();
    geometry.clearGroups();
    for (const entry of groups) {
      const previous = geometry.groups.at(-1);
      if (previous && previous.materialIndex === entry.materialIndex && previous.start + previous.count === entry.start) previous.count += entry.count;
      else geometry.addGroup(entry.start, entry.count, entry.materialIndex);
    }
    return geometry;
  }

  function faceTexture(expression: Expression) {
    const canvas = document.createElement("canvas");
    canvas.width = 1024;
    canvas.height = 1024;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Canvas is unavailable");
    context.fillStyle = "#ffebde";
    context.fillRect(0, 0, 1024, 1024);
    context.translate(512, 1024 * 1.1 / 2);
    context.scale(1024 / 1.6, -1024 / 2);
    context.lineCap = "round";
    context.lineJoin = "round";

    for (const side of [-1, 1]) {
      context.save();
      context.scale(side, 1);
      const cheek = context.createRadialGradient(0.44, -0.24, 0, 0.44, -0.24, 0.17);
      cheek.addColorStop(0, expression === "happy" ? "#e986918c" : "#ed9ba06a");
      cheek.addColorStop(1, "#ed9ba000");
      context.fillStyle = cheek;
      context.fillRect(0.21, -0.39, 0.46, 0.28);
      context.strokeStyle = "#bf71795c";
      context.lineWidth = 0.005;
      for (let index = 0; index < 5; index++) {
        const x = 0.34 + index * 0.033;
        context.beginPath(); context.moveTo(x, -0.22); context.lineTo(x - 0.025, -0.29); context.stroke();
      }
      const closed = expression === "happy" || expression === "blink";
      if (closed) {
        context.strokeStyle = "#392d3f";
        context.lineWidth = 0.018;
        context.beginPath(); context.moveTo(0.12, -0.035);
        context.quadraticCurveTo(0.32, expression === "happy" ? 0.14 : -0.15, 0.55, 0.015); context.stroke();
      } else {
        context.save();
        context.beginPath();
        context.moveTo(0.11, -0.015);
        context.bezierCurveTo(0.21, 0.12, 0.40, 0.17, 0.55, 0.075);
        context.bezierCurveTo(0.51, -0.12, 0.27, -0.15, 0.11, -0.015);
        context.closePath();
        context.fillStyle = "#fffdfa"; context.fill(); context.clip();
        const iris = context.createLinearGradient(0, 0.15, 0, -0.15);
        iris.addColorStop(0, "#133854"); iris.addColorStop(0.35, "#247ab7"); iris.addColorStop(0.73, "#64d1e9"); iris.addColorStop(1, "#c1ffff");
        context.beginPath(); context.ellipse(0.335, -0.008, 0.098, 0.147, 0, 0, Math.PI * 2);
        context.fillStyle = iris; context.fill(); context.strokeStyle = "#253856"; context.lineWidth = 0.012; context.stroke();
        context.strokeStyle = "#b4f9ff9c"; context.lineWidth = 0.006;
        for (let index = 0; index < 11; index++) {
          const angle = index / 11 * Math.PI;
          context.beginPath(); context.moveTo(0.335 + Math.cos(angle) * 0.056, -0.025 - Math.sin(angle) * 0.055);
          context.lineTo(0.335 + Math.cos(angle) * 0.082, -0.025 - Math.sin(angle) * 0.101); context.stroke();
        }
        context.fillStyle = "#132b47";
        context.beginPath(); context.ellipse(0.335, 0.014, 0.034, 0.077, 0, 0, Math.PI * 2); context.fill();
        context.fillStyle = "#ffffff";
        context.beginPath(); context.ellipse(0.302, 0.07, 0.025, 0.037, -0.2, 0, Math.PI * 2); context.fill();
        context.beginPath(); context.ellipse(0.381, -0.065, 0.012, 0.018, 0, 0, Math.PI * 2); context.fill();
        if (expression === "read") {
          context.fillStyle = "#ffebde"; context.fillRect(0, 0.068, 0.7, 0.2);
        }
        context.restore();
        context.strokeStyle = "#765461"; context.lineWidth = 0.006;
        context.beginPath(); context.moveTo(0.17, -0.067); context.quadraticCurveTo(0.38, -0.18, 0.53, -0.02); context.stroke();
        context.fillStyle = "#332839";
        context.beginPath(); context.moveTo(0.10, -0.015);
        context.bezierCurveTo(0.22, 0.135, 0.40, 0.178, 0.55, 0.086);
        context.lineTo(0.60, 0.14); context.lineTo(0.563, 0.053);
        context.bezierCurveTo(0.40, 0.139, 0.23, 0.094, 0.10, -0.015); context.fill();
        for (let index = 0; index < 3; index++) {
          context.beginPath(); context.moveTo(0.46 + index * 0.027, 0.118 - index * 0.008);
          context.lineTo(0.485 + index * 0.034, 0.17 - index * 0.007);
          context.lineTo(0.483 + index * 0.027, 0.11 - index * 0.008); context.fill();
        }
      }
      context.strokeStyle = "#94808f"; context.lineWidth = 0.014;
      context.beginPath(); context.moveTo(0.14, 0.27);
      context.quadraticCurveTo(0.34, expression === "happy" ? 0.37 : 0.32, 0.53, 0.26); context.stroke();
      context.restore();
    }
    context.strokeStyle = "#c68c87"; context.lineWidth = 0.009;
    context.beginPath(); context.moveTo(0.007, -0.21); context.lineTo(-0.012, -0.26); context.stroke();
    context.strokeStyle = "#895c68"; context.lineWidth = 0.011;
    context.beginPath(); context.moveTo(-0.087, -0.46);
    if (expression === "happy") context.quadraticCurveTo(0, -0.545, 0.087, -0.46);
    else context.bezierCurveTo(-0.026, -0.425, 0.023, -0.505, 0.088, -0.46);
    context.stroke();
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = 4;
    textures.add(texture);
    return texture;
  }

  const faces = Object.fromEntries((["idle", "happy", "read", "blink"] as Expression[]).map(expression => [expression, faceTexture(expression)])) as Record<Expression, THREE.CanvasTexture>;
  const faceMaterial = material("#ffffff");
  faceMaterial.map = faces.idle;

  // Swept elliptical cross sections form pointed, continuous locks instead of rounded capsules.
  function lock(parent: THREE.Object3D, points: Point[], width: number, depth: number, color: THREE.Material) {
    const curve = new THREE.CatmullRomCurve3(points.map(p => new THREE.Vector3(...p)));
    const vertices: number[] = [], indices: number[] = [];
    const rows = 32, columns = 10;
    for (let row = 0; row <= rows; row++) {
      const t = row / rows;
      const center = curve.getPoint(t), tangent = curve.getTangent(t);
      const side = new THREE.Vector3(-tangent.y, tangent.x, 0).normalize();
      const normal = new THREE.Vector3().crossVectors(side, tangent).normalize();
      const taper = Math.max(0.008, Math.pow(Math.sin(Math.PI * (0.15 + t * 0.85)), 0.72));
      for (let col = 0; col <= columns; col++) {
        const angle = col / columns * Math.PI * 2;
        const point = center.clone().addScaledVector(side, Math.cos(angle) * width * taper).addScaledVector(normal, Math.sin(angle) * depth * taper);
        vertices.push(point.x, point.y, point.z);
      }
    }
    for (let row = 0; row < rows; row++) for (let col = 0; col < columns; col++) {
      const a = row * (columns + 1) + col, b = a + columns + 1;
      indices.push(a, b, a + 1, a + 1, b, b + 1);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
    geometry.setIndex(indices); geometry.computeVertexNormals();
    return mesh(parent, geometry, color);
  }

  const root = new THREE.Group();
  const body = group(root);
  const head = group(body, [0, 2.83, 0]);
  head.name = "head";
  mesh(head, surface([
    [-0.84, 0.015, 0.08, 0.1], [-0.74, 0.20, 0.26, 0.04], [-0.58, 0.41, 0.40, 0],
    [-0.35, 0.56, 0.48, 0], [-0.08, 0.635, 0.505, 0], [0.2, 0.655, 0.52, -0.01],
    [0.5, 0.63, 0.49, -0.035], [0.76, 0.45, 0.37, -0.06], [0.91, 0.025, 0.04, -0.06],
  ], true), [skin, faceMaterial]);
  for (const side of [-1, 1]) ball(head, skin, [side * 0.62, -0.12, -0.02], [0.085, 0.17, 0.11]);

  // The crown joins the long back hair; front locks stay clear of the eyes.
  mesh(head, new THREE.SphereGeometry(1, 48, 24, 0, Math.PI * 2, 0, 1.1), silver, [0, 0.06, -0.04], [0.73, 0.97, 0.6]);
  const hairBack = group(head);
  for (let index = 0; index < 15; index++) {
    const angle = Math.PI / 2 + index / 14 * Math.PI;
    const x = Math.sin(angle), z = Math.cos(angle);
    lock(hairBack, [
      [x * 0.54, 0.64, z * 0.47 - 0.07], [x * 0.73, -0.05, z * 0.59 - 0.08],
      [x * 0.79, -1.0, z * 0.47 - 0.10], [x * 0.82, -1.96 + Math.sin(index * 1.9) * 0.15, z * 0.34 - 0.06],
    ], 0.17, 0.058, index % 3 === 0 ? silverShade : silver);
  }
  const bangs: Array<{ points: Point[]; width: number }> = [
    { points: [[-0.10, 0.95, 0.13], [-0.20, 0.62, 0.46], [-0.27, 0.35, 0.56], [-0.43, 0.10, 0.53]], width: 0.15 },
    { points: [[-0.03, 0.97, 0.16], [0.07, 0.60, 0.53], [0.05, 0.25, 0.60], [-0.10, -0.16, 0.56]], width: 0.135 },
    { points: [[0.07, 0.96, 0.14], [0.22, 0.60, 0.49], [0.21, 0.33, 0.56], [0.16, 0.12, 0.58]], width: 0.12 },
    { points: [[0.22, 0.88, 0.15], [0.42, 0.53, 0.43], [0.49, 0.33, 0.51], [0.57, 0.14, 0.45]], width: 0.14 },
    { points: [[-0.28, 0.85, 0.14], [-0.47, 0.42, 0.43], [-0.56, 0.18, 0.46], [-0.59, -0.13, 0.35]], width: 0.15 },
  ];
  bangs.forEach((bang, index) => lock(head, bang.points, bang.width, 0.038, index % 2 ? pearl : silver));
  for (const side of [-1, 1]) {
    lock(head, [[side * 0.42, 0.76, 0.08], [side * 0.68, 0.12, 0.27], [side * 0.65, -0.46, 0.33], [side * 0.46, -0.9, 0.43]], 0.13, 0.045, pearl);
    lock(head, [[side * 0.61, 0.50, -0.01], [side * 0.73, -0.34, 0.11], [side * 0.75, -1.14, 0.31], [side * 0.62, -1.75, 0.47]], 0.12, 0.046, silver);
    lock(head, [[side * 0.69, -0.13, -0.04], [side * 0.85, -0.70, 0.06], [side * 0.86, -1.22, 0.23], [side * 0.95, -1.60, 0.27]], 0.1, 0.035, pearl);
  }
  const ribbon = group(head, [-0.74, -0.24, 0.02]);
  ribbon.rotation.set(0.04, -0.3, -0.18);
  tube(ribbon, crimson, [[0, 0, 0], [-0.21, 0.20, 0], [-0.31, 0.15, 0], [-0.21, -0.04, 0], [0, 0, 0]], 0.026);
  tube(ribbon, crimson, [[0, 0, 0], [0.04, 0.22, 0], [0.17, 0.17, 0], [0.14, -0.06, 0], [0, 0, 0]], 0.026);
  box(ribbon, ribbonLight, [0, 0, 0.02], [0.09, 0.11, 0.06]);
  lock(ribbon, [[-0.07, -0.05, 0], [-0.12, -0.40, 0.05], [-0.05, -0.73, 0.04]], 0.039, 0.01, crimson);
  lock(ribbon, [[0.05, -0.05, 0], [0.06, -0.48, 0.03], [0.16, -0.80, 0.02]], 0.036, 0.01, crimson);

  mesh(body, surface([[1.73, 0.25, 0.21, -0.06], [1.96, 0.18, 0.17, -0.07], [2.23, 0.19, 0.18, -0.08]]), skin);
  mesh(body, surface([
    [0.20, 0.69, 0.34, -0.05], [0.42, 0.69, 0.34, -0.06], [0.84, 0.78, 0.40, -0.06],
    [1.22, 0.91, 0.42, -0.08], [1.58, 1.08, 0.33, -0.10], [1.78, 1.00, 0.24, -0.11],
    [1.89, 0.49, 0.18, -0.08], [1.95, 0.23, 0.19, -0.07],
  ]), cloth);
  box(body, navy, [0, 1.48, 0.04], [0.68, 0.45, 0.38]);
  box(body, cloth, [0, 1.82, 0.38], [0.21, 0.31, 0.055]);
  box(body, crimson, [0, 1.86, 0.445], [0.06, 0.16, 0.025]);
  box(body, crimson, [-0.09, 1.73, 0.44], [0.11, 0.11, 0.03]).rotation.z = -0.35;
  box(body, crimson, [0.09, 1.73, 0.44], [0.11, 0.11, 0.03]).rotation.z = 0.35;
  ball(body, gold, [0, 1.75, 0.47], [0.035, 0.035, 0.02]);
  const collar = mesh(body, new THREE.TorusGeometry(0.23, 0.031, 10, 48), seam, [0, 1.945, -0.07]);
  collar.rotation.x = Math.PI / 2;
  collar.scale.y = 0.79;
  for (const side of [-1, 1]) {
    tube(body, seam, [[side * 0.35, 1.87, 0.065], [side * 0.7, 1.77, 0.15], [side * 0.93, 1.62, 0.17]], 0.009);
    tube(body, seam, [[side * 0.64, 1.05, 0.27], [side * 0.60, 0.74, 0.27], [side * 0.64, 0.45, 0.14]], 0.007);
  }
  const skirt = mesh(body, new THREE.CylinderGeometry(0.46, 0.7, 0.54, 24), navy, [0, 0.78, 0]);
  skirt.scale.z = 0.72;
  const skirtBand = mesh(body, new THREE.TorusGeometry(0.45, 0.035, 10, 32), crimson, [0, 1.05, 0]);
  skirtBand.scale.z = 0.72;
  for (const side of [-1, 1]) {
    ball(body, skin, [side * 0.19, 0.42, 0], [0.115, 0.18, 0.12]);
    mesh(body, new THREE.CapsuleGeometry(0.13, 0.33, 8, 16), cloth, [side * 0.19, 0.02, 0]);
    box(body, crimson, [side * 0.19, 0.20, 0.04], [0.14, 0.035, 0.14]);
    box(body, cloth, [side * 0.19, -0.34, 0.12], [0.26, 0.14, 0.46]);
    box(body, crimson, [side * 0.19, -0.24, 0.27], [0.25, 0.07, 0.12]);
  }

  function makeArm(side: number) {
    const arm = group(body, [side * 1.0, 1.72, -0.06]);
    arm.rotation.z = side * 0.10;
    mesh(arm, surface([[-0.63, 0.145, 0.145, 0.02], [-0.38, 0.18, 0.18, 0], [-0.07, 0.22, 0.22, 0], [0.10, 0.14, 0.14, 0]]), cloth);
    const forearm = group(arm, [0, -0.54, 0.025]);
    mesh(forearm, surface([[-0.44, 0.11, 0.11, 0.025], [-0.20, 0.13, 0.13, 0.02], [0.04, 0.15, 0.15, 0]]), cloth);
    ball(forearm, cloth, [0, -0.42, 0.025], [0.124, 0.074, 0.13]);
    const hand = group(forearm, [0, -0.54, 0.025]);
    ball(hand, skin, [0, -0.015, 0], [0.10, 0.13, 0.045]);
    for (let finger = 0; finger < 4; finger++) {
      const x = (finger - 1.5) * 0.043;
      const length = finger === 1 || finger === 2 ? 0.18 : 0.145;
      ball(hand, skin, [x, -0.105 - length / 2, 0.005], [0.023, length / 2, 0.027]);
    }
    const thumb = ball(hand, skin, [-side * 0.1, -0.02, 0.02], [0.031, 0.085, 0.029]);
    thumb.rotation.z = -side * 0.43;
    return { arm, forearm };
  }
  const left = makeArm(-1), right = makeArm(1);
  right.forearm.rotation.x = -0.7;
  right.forearm.rotation.z = -0.20;
  const book = group(right.forearm, [-0.03, -0.35, 0.14]);
  book.name = "book";
  book.rotation.set(0.59, 0.08, 0.15);
  box(book, bookCover, [0, 0.20, 0], [0.42, 0.57, 0.11]);
  box(book, cloth, [0.014, 0.20, 0], [0.38, 0.52, 0.076]);
  box(book, bookCover, [0, 0.20, 0.054], [0.42, 0.57, 0.022]);
  box(book, crimson, [0, 0.20, 0.069], [0.31, 0.31, 0.01]);
  const diamond = mesh(book, new THREE.OctahedronGeometry(0.075), gold, [0, 0.20, 0.095]);
  diamond.scale.z = 0.2;
  for (const y of [0.41, -0.01]) box(book, gold, [0, y, 0.07], [0.25, 0.01, 0.008]);

  const particles = group(root, [0, 2.3, 0]);
  for (let index = 0; index < 8; index++) mesh(particles, new THREE.OctahedronGeometry(0.045), index % 2 ? crimson : gold);
  particles.visible = false;
  let elapsed = 0, actionTime = 10;
  let action: MascotAction = "wave";
  let currentExpression: Expression = "idle";
  return {
    root,
    react(next: MascotAction, animate: boolean) {
      action = next;
      actionTime = animate ? 0 : 1.1;
      this.update(0, 0, 0, animate);
    },
    update(delta: number, pointerX: number, pointerY: number, animate: boolean) {
      if (animate) { elapsed += delta; actionTime += delta; }
      const active = actionTime < 2.5;
      const envelope = active ? Math.sin(Math.PI * actionTime / 2.5) : 0;
      const idle = animate ? Math.sin(elapsed * 1.4) : 0;
      body.rotation.y = -0.07 + pointerX * 0.045;
      body.position.y = idle * 0.01;
      head.rotation.y = pointerX * 0.10;
      head.rotation.x = -pointerY * 0.05 + (action === "read" ? envelope * 0.13 : 0);
      head.rotation.z = idle * 0.009 + (action === "happy" ? envelope * -0.09 : 0);
      hairBack.rotation.z = idle * 0.008;
      const wave = action === "wave" ? envelope : 0;
      left.arm.rotation.z = -0.10 - wave * 0.25;
      left.forearm.rotation.z = -wave * (2.5 + Math.sin(actionTime * 13) * 0.15);
      right.forearm.rotation.x = -0.7 - (action === "read" ? envelope * 0.3 : 0);
      const expression: Expression = active && action === "happy" ? "happy" : animate && elapsed % 4.6 > 4.44 ? "blink" : active && action === "read" ? "read" : "idle";
      if (expression !== currentExpression) {
        faceMaterial.map = faces[expression];
        currentExpression = expression;
      }
      particles.visible = active && animate;
      particles.children.forEach((particle, index) => {
        const angle = index / 8 * Math.PI * 2 + actionTime * 0.2;
        particle.position.set(Math.cos(angle) * (1.04 + envelope * 0.14), Math.sin(angle) * 0.84 + actionTime * 0.07, 0.50);
        particle.rotation.set(actionTime, actionTime + index, index);
        particle.scale.setScalar(envelope);
      });
    },
    dispose() {
      geometries.forEach(value => value.dispose());
      materials.forEach(value => value.dispose());
      textures.forEach(value => value.dispose());
    },
  };
}
