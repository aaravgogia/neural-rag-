/**
 * The signature structural element of this app: a schematic rendering of
 * the actual LangGraph pipeline (analyze -> cache -> retrieve -> generate
 * -> grade), used as a recurring motif across pages -- not a logo, not a
 * decoration. On the live demo it reflects real node state; everywhere
 * else it's a static wayfinding device that says "this is a system with
 * a real, inspectable execution path" before a single word of copy loads.
 *
 * states: 'idle' (default, used on marketing pages) | node-state map
 */
const DEFAULT_STEPS = [
  { key: 'analyze_query',      label: 'ANALYZE' },
  { key: 'check_cache',        label: 'CACHE' },
  { key: 'retrieve_documents', label: 'RETRIEVE' },
  { key: 'generate_answer',    label: 'GENERATE' },
  { key: 'grade_answer',       label: 'GRADE' },
];

export default function PipelineStrip({ trace = {}, size = 'default', nodes }) {
  const steps = nodes || DEFAULT_STEPS;
  const dotSize = size === 'sm' ? 'w-[5px] h-[5px]' : 'w-1.5 h-1.5';
  const gap = size === 'sm' ? 'gap-3' : 'gap-4';
  const textSize = size === 'sm' ? 'text-[9px]' : 'text-[10px]';

  return (
    <div className={`flex items-center ${gap} font-mono ${textSize} tracking-wider select-none`}>
      {steps.map((step, i) => {
        const state = trace[step.key]?.status ?? 'idle';
        return (
          <div key={step.key} className="flex items-center">
            <div className="flex items-center gap-1.5">
              <span
                className={`${dotSize} rounded-full transition-all duration-300 ${
                  state === 'done' ? 'bg-trace shadow-[0_0_6px_rgba(79,216,196,0.6)]' :
                  state === 'active' ? 'bg-pulse shadow-[0_0_8px_rgba(255,122,69,0.6)] animate-pulse' :
                  'bg-mute/40'
                }`}
              />
              <span className={state === 'idle' ? 'text-mute/60' : state === 'active' ? 'text-pulse' : 'text-trace'}>
                {step.label}
              </span>
            </div>
            {i < steps.length - 1 && (
              <div className="w-5 h-px bg-line mx-2" />
            )}
          </div>
        );
      })}
    </div>
  );
}
