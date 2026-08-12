import { motion, AnimatePresence } from 'framer-motion';
import { Globe2, Users, Zap } from 'lucide-react';
import PipelineStrip from '../shared/PipelineStrip';

const NODE_LABELS = {
  analyze_query: 'Analyze', check_cache: 'Cache', retrieve_documents: 'Retrieve',
  generate_answer: 'Generate', grade_answer: 'Grade', web_search_fallback: 'Web search',
};
const BASE_NODE_ORDER = ['analyze_query', 'check_cache', 'retrieve_documents', 'generate_answer', 'grade_answer'];

/**
 * Live agent trace, restyled to the schematic/instrumentation design
 * language: hairline panel, monospace data readouts, trace/pulse signal
 * colors instead of gradient icon badges.
 */
export default function AgentTracePanel({ trace, viewerCount, cacheHit, evalMetrics }) {
  if (!trace || Object.keys(trace).length === 0) return null;
  const nodeOrder = BASE_NODE_ORDER.flatMap(key => key === 'grade_answer' && trace.web_search_fallback
    ? [key, 'web_search_fallback'] : [key]);
  const pipelineNodes = nodeOrder.map(key => ({ key, label: NODE_LABELS[key] || key.replaceAll('_', ' ').toUpperCase() }));

  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="panel rounded-lg p-4 mb-4 font-mono"
    >
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] text-mute tracking-wider">AGENT TRACE · LIVE</span>
        {viewerCount > 1 && (
          <div className="flex items-center gap-1.5 text-[10px] text-trace border border-line-2 px-2 py-0.5 rounded">
            <Users className="w-3 h-3" />
            {viewerCount} viewing
          </div>
        )}
      </div>

      <PipelineStrip trace={trace} nodes={pipelineNodes} />

      <div className="mt-3 space-y-1 text-[11px] text-mute">
        {nodeOrder.map(key => {
          const n = trace[key];
          if (!n || n.durationMs == null) return null;
          return (
            <div key={key} className="flex items-center justify-between">
              <span>{NODE_LABELS[key]}</span>
              <span className="text-paper/70">{n.durationMs}ms</span>
            </div>
          );
        })}
      </div>

      {trace.retrieve_documents?.result?.top_scores && (
        <div className="mt-3 pt-3 border-t border-line text-[11px] text-mute">
          retrieved {trace.retrieve_documents.result.chunks_found} chunks · fused ={' '}
          <span className="text-paper/80">
            {trace.retrieve_documents.result.top_scores.map(s => s.toFixed(3)).join(', ')}
          </span>
          {trace.retrieve_documents.result.reranking_applied && (
            <span className="ml-2 text-trace">Â· cross-encoder reranked</span>
          )}
        </div>
      )}

      {trace.web_search_fallback && (
        <div className="mt-3 pt-3 border-t border-line text-[11px] flex items-center gap-1.5 text-pulse">
          <Globe2 className="w-3 h-3" /> external search {trace.web_search_fallback.result?.results_found ? `added ${trace.web_search_fallback.result.results_found} sources` : 'skipped (not configured or no results)'}
        </div>
      )}

      {cacheHit && (
        <div className="mt-2 text-[11px] text-pulse flex items-center gap-1.5">
          <Zap className="w-3 h-3" /> served from semantic cache
          {trace.check_cache?.result?.similarity != null && ` (sim ${trace.check_cache.result.similarity})`}
        </div>
      )}

      {evalMetrics && Object.keys(evalMetrics).length > 0 && (
        <div className="mt-3 pt-3 border-t border-line grid grid-cols-3 gap-2 text-center">
          <div>
            <div className="text-sm text-paper">{(evalMetrics.groundedness * 100).toFixed(0)}%</div>
            <div className="text-[9px] text-mute">groundedness</div>
          </div>
          <div>
            <div className="text-sm text-paper">{evalMetrics.retrieval_relevance}</div>
            <div className="text-[9px] text-mute">relevance</div>
          </div>
          <div>
            <div className="text-sm text-paper">{evalMetrics.num_sources}</div>
            <div className="text-[9px] text-mute">sources</div>
          </div>
        </div>
      )}
    </motion.div>
  );
}
