import { lazy, Suspense, useEffect, useState } from 'react';
import ParticleBackground from '../ui/ParticleBackground';

const PipelineHero3D = lazy(() => import('./PipelineHero3D'));

function useRenderMode() {
  const [mode, setMode] = useState(null);
  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const lowCoreCount = typeof navigator.hardwareConcurrency === 'number' && navigator.hardwareConcurrency <= 4;
    if (reduced || lowCoreCount) { setMode('fallback'); return undefined; }
    let frames = 0;
    let frameId;
    const started = performance.now();
    const sample = () => {
      frames += 1;
      if (performance.now() - started >= 450) {
        setMode(frames < 20 ? 'fallback' : 'three');
      } else frameId = requestAnimationFrame(sample);
    };
    frameId = requestAnimationFrame(sample);
    return () => cancelAnimationFrame(frameId);
  }, []);
  return mode;
}

export default function AdaptivePipelineHero() {
  const mode = useRenderMode();
  if (mode === 'fallback') return <ParticleBackground />;
  if (mode !== 'three') return <div className="absolute inset-0 signal-grid opacity-25" aria-hidden="true" />;
  return <Suspense fallback={<ParticleBackground />}><PipelineHero3D /></Suspense>;
}
