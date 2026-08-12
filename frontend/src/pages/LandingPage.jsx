import { motion, useScroll, useTransform } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useEffect, useRef, useState } from 'react';
import PipelineStrip from '../components/shared/PipelineStrip';
import AdaptivePipelineHero from '../components/hero/AdaptivePipelineHero';
import { ArrowUpRight, Github } from 'lucide-react';

// Real measured results from this project's own test suite and dev logs --
// not invented marketing numbers. See EXTRAORDINARY_FEATURES.md for the
// raw output each of these is drawn from.
const PROOF_POINTS = [
  { value: '14/14', label: 'pytest cases passing', detail: 'retrieval, routing + rate limits' },
  { value: '3', label: 'rankers fused', detail: 'BM25 + TF-IDF cosine + MMR diversity' },
  { value: '2', label: 'concurrent clients verified', detail: 'identical 54/55-event WebSocket stream' },
  { value: '5', label: 'graph nodes traced live', detail: 'analyze → cache → retrieve → generate → grade' },
];

function ScrollReveal({ children, className = '' }) {
  const ref = useRef(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start 92%', 'start 45%'] });
  const opacity = useTransform(scrollYProgress, [0, 1], [0.18, 1]);
  const y = useTransform(scrollYProgress, [0, 1], [24, 0]);
  return <motion.div ref={ref} style={{ opacity, y }} className={className}>{children}</motion.div>;
}

const PIPELINE_SPEC = [
  {
    n: '01', key: 'ANALYZE',
    title: 'Query analysis & routing',
    body: 'Decides whether the question needs retrieval at all -- greetings and chit-chat skip straight to a response instead of wastefully querying the index.',
  },
  {
    n: '02', key: 'CACHE',
    title: 'Semantic cache lookup',
    body: 'Checks for a near-duplicate question by cosine similarity, not exact string match. "What\u2019s the refund policy" and "refund policy?" hit the same cache entry.',
  },
  {
    n: '03', key: 'RETRIEVE',
    title: 'Hybrid search',
    body: 'BM25 (lexical) and a dense vector index are queried in parallel, then fused with Reciprocal Rank Fusion and re-ranked with MMR for result diversity.',
  },
  {
    n: '04', key: 'GENERATE',
    title: 'Grounded generation',
    body: 'The model answers strictly from retrieved passages, streamed token-by-token over WebSocket to every client watching the session.',
  },
  {
    n: '05', key: 'GRADE',
    title: 'Self-evaluation & retry',
    body: 'A groundedness score is computed from real word-overlap against the retrieved context. Low-confidence answers trigger one automatic retry with re-retrieval.',
  },
];

export default function LandingPage() {
  const navigate = useNavigate();
  const [heroTrace, setHeroTrace] = useState({});

  // One orchestrated moment, not a particle field: the pipeline strip in the
  // hero "boots up" once on load, node by node, to demonstrate -- in the
  // first two seconds, before any copy is read -- that this is a system
  // with a real, steppable execution path.
  useEffect(() => {
    const keys = ['analyze_query', 'check_cache', 'retrieve_documents', 'generate_answer', 'grade_answer'];
    keys.forEach((k, i) => {
      setTimeout(() => setHeroTrace(t => ({ ...t, [k]: { status: 'active' } })), i * 350);
      setTimeout(() => setHeroTrace(t => ({ ...t, [k]: { status: 'done' } })), i * 350 + 280);
    });
  }, []);

  return (
    <div className="min-h-screen bg-ink text-paper font-sans">
      {/* Nav */}
      <nav className="border-b border-line">
        <div className="max-w-5xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="font-mono text-sm tracking-tight">
            <span className="text-paper">neuralrag</span>
            <span className="text-mute">://pipeline</span>
          </div>
          <div className="flex items-center gap-6 font-mono text-xs text-mute">
            <a href="#pipeline" className="hover:text-paper transition-colors">how it thinks</a>
            <a href="#proof" className="hover:text-paper transition-colors">proof</a>
            <button onClick={() => navigate('/status')} className="hover:text-paper transition-colors">status</button>
            <button
              onClick={() => navigate('/live-demo')}
              className="flex items-center gap-1.5 text-paper border border-line-2 rounded px-3 py-1.5 hover:border-trace hover:text-trace transition-colors"
            >
              run it live <ArrowUpRight className="w-3 h-3" />
            </button>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="max-w-5xl mx-auto px-6 pt-16 md:pt-20 pb-16 grid lg:grid-cols-[1.05fr_.95fr] gap-10 items-center">
        <div>
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="font-mono text-xs text-trace mb-6 tracking-wider">
          SYS · LANGGRAPH + HYBRID RETRIEVAL · TRACE ENABLED
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}
          className="font-display text-5xl md:text-6xl font-medium leading-[1.08] mb-6 max-w-3xl"
        >
          Retrieval-augmented generation, <span className="text-mute">observed.</span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
          className="text-mute text-lg leading-relaxed max-w-xl mb-10"
        >
          A hybrid-search RAG agent built on LangGraph, with every retrieval score,
          cache decision, and retry visible in real time -- not a black box that
          occasionally cites a source.
        </motion.p>

        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }} className="flex items-center gap-3 mb-16">
          <button
            onClick={() => navigate('/live-demo')}
            className="bg-paper text-ink font-medium text-sm px-5 py-3 rounded hover:bg-trace transition-colors flex items-center gap-2"
          >
            Run it live <ArrowUpRight className="w-4 h-4" />
          </button>
          <a
            href="#pipeline"
            className="border border-line-2 text-paper font-medium text-sm px-5 py-3 rounded hover:border-mute transition-colors"
          >
            Read the trace
          </a>
        </motion.div>

        {/* Live-booting pipeline schematic -- the actual signature element */}
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }}
          className="panel rounded-lg p-6 overflow-x-auto"
        >
          <PipelineStrip trace={heroTrace} />
        </motion.div>
        </div>
        <motion.div initial={{ opacity: 0, scale: .98 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: .18 }} className="relative h-72 md:h-80 lg:h-[360px] overflow-hidden rounded-lg border border-line bg-ink-2">
          <AdaptivePipelineHero />
          <div className="absolute left-4 top-4 font-mono text-[10px] tracking-wider text-trace">LIVE TOPOLOGY</div>
          <div className="absolute right-4 top-4 flex items-center gap-1.5 font-mono text-[9px] text-mute"><span className="w-1.5 h-1.5 rounded-full bg-pulse animate-pulse" />FLOWING</div>
        </motion.div>
      </section>

      {/* Proof strip -- real numbers, not marketing claims */}
      <section id="proof" className="border-y border-line">
        <ScrollReveal className="max-w-5xl mx-auto px-6 py-10 grid grid-cols-2 md:grid-cols-4 gap-8">
          {PROOF_POINTS.map((p, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.05 }}
            >
              <div className="font-display text-3xl mb-1">{p.value}</div>
              <div className="text-sm text-paper mb-0.5">{p.label}</div>
              <div className="font-mono text-[11px] text-mute">{p.detail}</div>
            </motion.div>
          ))}
        </ScrollReveal>
      </section>

      {/* Pipeline spec -- annotated, not icon cards */}
      <section id="pipeline" className="max-w-5xl mx-auto px-6 py-20">
        <ScrollReveal className="mb-12">
          <div className="font-mono text-xs text-mute mb-2">HOW IT THINKS</div>
          <h2 className="font-display text-3xl">Five nodes. One state machine.</h2>
        </ScrollReveal>

        <div className="space-y-0">
          {PIPELINE_SPEC.map((step, i) => (
            <motion.div
              key={step.n}
              initial={{ opacity: 0, y: 12 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, amount: .3 }}
              className={`relative grid grid-cols-[auto_1fr] md:grid-cols-[80px_160px_1fr] gap-4 md:gap-8 py-6 border-t border-line ${i === PIPELINE_SPEC.length - 1 ? 'border-b' : ''}`}
            >
              <motion.div initial={{ scaleX: 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true }} transition={{ duration: .55, delay: .08 }} className="absolute left-0 top-0 h-px w-full origin-left bg-trace/50" />
              <div className="font-mono text-mute text-sm">{step.n}</div>
              <div className="font-mono text-xs text-trace tracking-wider self-start">{step.key}</div>
              <div className="col-span-2 md:col-span-1">
                <h3 className="font-display text-lg mb-1.5">{step.title}</h3>
                <p className="text-mute text-sm leading-relaxed max-w-lg">{step.body}</p>
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Honest scope section -- this is the recruiter-credibility move:
          stating exactly what's real vs. stubbed is more impressive than
          pretending everything is production-perfect. */}
      <section className="border-t border-line">
        <ScrollReveal className="max-w-5xl mx-auto px-6 py-16">
          <div className="font-mono text-xs text-mute mb-2">SCOPE</div>
          <h2 className="font-display text-2xl mb-8">What's real vs. what's stubbed</h2>
          <div className="grid md:grid-cols-2 gap-6">
            <div className="panel rounded-lg p-5">
              <div className="text-trace font-mono text-xs mb-3">✓ REAL, RUNNING, TESTED</div>
              <ul className="text-sm text-paper/90 space-y-2 leading-relaxed">
                <li>Hybrid retrieval (BM25 + TF-IDF + RRF + MMR)</li>
                <li>LangGraph state machine with conditional routing &amp; retry</li>
                <li>WebSocket broadcast to multiple concurrent clients</li>
                <li>Semantic cache with cosine-similarity lookup</li>
                <li>Groundedness &amp; relevance metrics computed from real text</li>
              </ul>
            </div>
            <div className="panel rounded-lg p-5">
              <div className="text-pulse font-mono text-xs mb-3">→ SWAPPABLE FOR PRODUCTION</div>
              <ul className="text-sm text-paper/90 space-y-2 leading-relaxed">
                <li>Answer generation uses an extractive stub, not a paid LLM API</li>
                <li>Dense retrieval uses TF-IDF as an embedding-interface stand-in</li>
                <li>Both are single-line swaps -- see <code className="font-mono text-xs text-mute">stub_llm.py</code></li>
              </ul>
            </div>
          </div>
        </ScrollReveal>
      </section>

      {/* Footer */}
      <footer className="border-t border-line">
        <div className="max-w-5xl mx-auto px-6 py-8 flex items-center justify-between">
          <div className="font-mono text-xs text-mute">neuralrag://pipeline</div>
          <div className="flex items-center gap-4 text-mute">
            <a href="#" className="hover:text-paper transition-colors flex items-center gap-1 text-xs font-mono">
              <Github className="w-3.5 h-3.5" /> source
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
