import { useEffect, useRef } from 'react';

/** Lightweight instrumentation-field fallback when WebGL or motion is unsuitable. */
export default function ParticleBackground({ className = 'absolute inset-0' }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!ctx) return undefined;
    let animationId;
    let particles = [];
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const resize = () => {
      const { width, height } = canvas.parentElement?.getBoundingClientRect() || window;
      canvas.width = width;
      canvas.height = height;
    };
    const reset = (particle) => Object.assign(particle, {
      x: Math.random() * canvas.width, y: Math.random() * canvas.height,
      vx: (Math.random() - .5) * .16, vy: (Math.random() - .5) * .16,
      radius: Math.random() * 1.4 + .5, opacity: Math.random() * .32 + .08,
      color: Math.random() > .22 ? '#4FD8C4' : '#FF7A45',
    });
    const init = () => {
      resize();
      particles = Array.from({ length: reduced ? 44 : 72 }, () => reset({}));
    };
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      particles.forEach((particle) => {
        if (!reduced) {
          particle.x += particle.vx; particle.y += particle.vy;
          if (particle.x < 0 || particle.x > canvas.width || particle.y < 0 || particle.y > canvas.height) reset(particle);
        }
        ctx.beginPath(); ctx.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
        ctx.fillStyle = particle.color; ctx.globalAlpha = particle.opacity; ctx.fill();
      });
      ctx.globalAlpha = 1;
      if (!reduced) animationId = requestAnimationFrame(draw);
    };
    init(); draw();
    window.addEventListener('resize', init);
    return () => { cancelAnimationFrame(animationId); window.removeEventListener('resize', init); };
  }, []);

  return <canvas aria-hidden="true" ref={canvasRef} className={`${className} pointer-events-none`} />;
}
