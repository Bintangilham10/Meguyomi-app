"use client";

import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Environment, Lightformer, OrbitControls } from "@react-three/drei";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { createYomiModel, type MascotAction } from "@/lib/yomi-model";

export interface MascotCommand { action: MascotAction; id: number }
interface ThreeMascotProps {
  paused: boolean;
  reducedMotion: boolean;
  active: boolean;
  command: MascotCommand;
  onReact: (action: MascotAction) => void;
  onReady: () => void;
  onUnavailable: () => void;
}

function StudioLighting() {
  return <>
    <Environment frames={1} resolution={128} environmentIntensity={0.45}>
      <color attach="background" args={["#647d80"]} />
      <Lightformer position={[-3, 4, 4]} rotation={[0, Math.PI / 4, 0]} scale={[4, 4, 1]} intensity={3} color="#fff0db" />
      <Lightformer position={[4, 2, 1]} rotation={[0, -Math.PI / 2, 0]} scale={[3, 4, 1]} intensity={2} color="#b9fff0" />
    </Environment>
    <ambientLight intensity={0.6} />
    <directionalLight position={[-3, 6, 5]} intensity={1.5} color="#fff2ed" castShadow shadow-mapSize={[1024, 1024]} shadow-camera-left={-3} shadow-camera-right={3} shadow-camera-top={4} shadow-camera-bottom={-3} shadow-normalBias={0.035} shadow-bias={-0.0001} />
    <directionalLight position={[4, 3, -3]} intensity={1.7} color="#b7d6ff" />
    <directionalLight position={[1, 0, 4]} intensity={0.4} color="#ffe2ec" />
    <mesh position={[0, 0.06, 0]} receiveShadow>
      <cylinderGeometry args={[1.15, 1.18, 0.13, 64]} />
      <meshStandardMaterial color="#283e49" roughness={0.46} metalness={0.3} />
    </mesh>
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.133, 0]}>
      <torusGeometry args={[1.02, 0.012, 8, 80]} />
      <meshStandardMaterial color="#9febd1" emissive="#77e1bd" emissiveIntensity={0.65} />
    </mesh>
  </>;
}

function YomiScene({ paused, reducedMotion, active, command, onReact, onReady, onUnavailable }: ThreeMascotProps) {
  const model = useMemo(() => createYomiModel(), []);
  const pointer = useRef({ x: 0, y: 0 });
  const lastCommand = useRef(0);
  const reportedReady = useRef(false);
  const { gl, invalidate, setFrameloop } = useThree();
  const animate = active && !paused && !reducedMotion;

  useEffect(() => () => model.dispose(), [model]);
  useEffect(() => {
    if (command.id !== lastCommand.current) {
      lastCommand.current = command.id;
      model.react(command.action, animate);
      invalidate();
    }
  }, [command, animate, model, invalidate]);

  useEffect(() => {
    setFrameloop(animate ? "always" : "demand");
    invalidate();
  }, [animate, invalidate, setFrameloop]);

  useFrame((_state, delta) => {
    model.update(Math.min(delta, 0.05), animate ? pointer.current.x : 0, animate ? pointer.current.y : 0, animate);
    if (!reportedReady.current) {
      reportedReady.current = true;
      onReady();
    }
  });

  useEffect(() => {
    const canvas = gl.domElement;
    const move = (event: PointerEvent) => {
      if (event.pointerType !== "mouse") return;
      const bounds = canvas.getBoundingClientRect();
      pointer.current.x = ((event.clientX - bounds.left) / bounds.width - 0.5) * 2;
      pointer.current.y = ((event.clientY - bounds.top) / bounds.height - 0.5) * 2;
    };
    const reset = () => { pointer.current = { x: 0, y: 0 }; };
    const lost = (event: Event) => { event.preventDefault(); onUnavailable(); };
    canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerleave", reset);
    canvas.addEventListener("webglcontextlost", lost);
    return () => {
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerleave", reset);
      canvas.removeEventListener("webglcontextlost", lost);
    };
  }, [gl, onUnavailable]);

  function interact(event: ThreeEvent<MouseEvent>) {
    // Orbit drags end with a click too; only short taps trigger a reaction.
    if (event.delta > 5) return;
    event.stopPropagation();
    let target: THREE.Object3D | null = event.object;
    let action: MascotAction = "wave";
    while (target) {
      if (target.name === "book") { action = "read"; break; }
      if (target.name === "head") { action = "happy"; break; }
      target = target.parent;
    }
    onReact(action);
  }

  return <>
    <StudioLighting />
    <primitive object={model.root} onClick={interact} />
    <OrbitControls target={[0, 2.42, 0]} enableZoom={false} enablePan={false} enableDamping={animate} dampingFactor={0.09} rotateSpeed={0.65} minPolarAngle={Math.PI / 2.4} maxPolarAngle={Math.PI / 1.95} makeDefault />
  </>;
}

export function ThreeMascot(props: ThreeMascotProps) {
  return <Canvas
    className="three-character-canvas"
    shadows
    dpr={[1, 1.5]}
    frameloop="demand"
    gl={{ antialias: true, alpha: true, powerPreference: "low-power" }}
    camera={{ position: [0.15, 2.7, 6.9], fov: 30, near: 0.1, far: 40 }}
  >
    <YomiScene {...props} />
  </Canvas>;
}
