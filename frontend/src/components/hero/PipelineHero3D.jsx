import { Canvas, useFrame } from '@react-three/fiber';
import { Line } from '@react-three/drei';
import { useMemo, useRef } from 'react';
import * as THREE from 'three';

const NODES = [
  { id: 'ANALYZE', position: [-2.55, .45, 0] },
  { id: 'RETRIEVE', position: [-1.2, -.36, .18] },
  { id: 'GENERATE', position: [0, .28, 0] },
  { id: 'GRADE', position: [1.35, -.18, .16] },
  { id: 'OUTPUT', position: [2.55, .38, 0] },
];

function Node({ position, index }) {
  const mesh = useRef();
  useFrame(({ clock }) => {
    const active = Math.sin(clock.elapsedTime * .85 - index * .8);
    if (mesh.current) mesh.current.scale.setScalar(1 + Math.max(0, active) * .12);
  });
  return <mesh ref={mesh} position={position}>
    <sphereGeometry args={[.13, 20, 20]} />
    <meshStandardMaterial color={index === 2 ? '#FF7A45' : '#4FD8C4'} emissive={index === 2 ? '#FF7A45' : '#4FD8C4'} emissiveIntensity={.72} roughness={.4} />
  </mesh>;
}

function Signal({ from, to, delay }) {
  const signal = useRef();
  const start = useMemo(() => new THREE.Vector3(...from), [from]);
  const end = useMemo(() => new THREE.Vector3(...to), [to]);
  useFrame(({ clock }) => {
    const progress = (clock.elapsedTime * .17 + delay) % 1;
    signal.current?.position.lerpVectors(start, end, progress);
  });
  return <mesh ref={signal}>
    <sphereGeometry args={[.052, 12, 12]} />
    <meshBasicMaterial color="#FF7A45" toneMapped={false} />
  </mesh>;
}

function PipelineMesh() {
  const group = useRef();
  useFrame(({ clock }) => {
    if (group.current) {
      group.current.rotation.y = Math.sin(clock.elapsedTime * .18) * .12;
      group.current.rotation.x = Math.cos(clock.elapsedTime * .14) * .035;
    }
  });
  return <group ref={group}>
    {NODES.map((node, index) => <Node key={node.id} position={node.position} index={index} />)}
    {NODES.slice(0, -1).map((node, index) => <group key={`${node.id}-edge`}>
      <Line points={[node.position, NODES[index + 1].position]} color="#4FD8C4" transparent opacity={.42} lineWidth={1} />
      <Signal from={node.position} to={NODES[index + 1].position} delay={index * .21} />
    </group>)}
  </group>;
}

export default function PipelineHero3D() {
  return <div className="absolute inset-0" aria-label="Animated LangGraph pipeline topology">
    <Canvas dpr={[1, 1.5]} camera={{ position: [0, 0, 6], fov: 38 }} gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}>
      <ambientLight intensity={.45} />
      <pointLight position={[1, 2, 3]} intensity={1.3} color="#4FD8C4" />
      <PipelineMesh />
    </Canvas>
    <div className="absolute inset-x-4 bottom-3 flex justify-between font-mono text-[9px] tracking-[.16em] text-mute/80">
      <span>ANALYZE</span><span>RETRIEVE</span><span>GENERATE</span><span>GRADE</span><span>OUTPUT</span>
    </div>
  </div>;
}
