import { motion, AnimatePresence } from 'framer-motion';
import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useWsChatStore } from '../store/wsChatStore';
import AgentTracePanel from '../components/chat/AgentTracePanel';
import { Send, ArrowLeft, Circle } from 'lucide-react';
import { CitationAnswer, SourcesPanel } from '../components/chat/Citations';

const SESSION_ID = 'live-demo-session';
const SUGGESTIONS = [
  'how long do I have to file expenses',
  'what does SOC 2 require for data retention',
  'what does invoice 4471 cover',
];

export default function LiveChatDemo() {
  const {
    connect, sendMessage, disconnect, connected, viewerCount,
    messages, streamingAnswer, trace, cacheHit, evalMetrics, isStreaming,
  } = useWsChatStore();
  const [input, setInput] = useState('');
  const bottomRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    connect(SESSION_ID);
    return () => disconnect();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingAnswer]);

  const handleSend = (q) => {
    const question = (q ?? input).trim();
    if (!question || isStreaming) return;
    sendMessage(question);
    setInput('');
  };

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  return (
    <div className="min-h-screen bg-ink text-paper font-sans flex flex-col items-center py-10 px-4">
      <div className="w-full max-w-2xl">
        <div className="flex items-center justify-between mb-8">
          <button onClick={() => navigate('/')} className="flex items-center gap-1.5 text-mute hover:text-paper transition-colors text-sm font-mono">
            <ArrowLeft className="w-3.5 h-3.5" /> back
          </button>
          <div className={`flex items-center gap-1.5 text-xs font-mono ${connected ? 'text-trace' : 'text-danger'}`}>
            <Circle className={`w-2 h-2 fill-current ${connected ? 'animate-pulse' : ''}`} />
            {connected ? 'connected' : 'disconnected'}
          </div>
        </div>

        <div className="mb-6">
          <h1 className="font-display text-2xl mb-1">Live agent, live trace.</h1>
          <p className="text-mute text-sm">
            Real LangGraph execution, streamed over WebSocket. Every node below reflects the actual backend state.
          </p>
        </div>

        <AnimatePresence>
          {(Object.keys(trace).length > 0 || isStreaming) && (
            <AgentTracePanel trace={trace} viewerCount={viewerCount} cacheHit={cacheHit} evalMetrics={evalMetrics} />
          )}
        </AnimatePresence>

        <div className="panel rounded-lg p-4 min-h-[320px] max-h-[420px] overflow-y-auto space-y-4 mb-4">
          {messages.length === 0 && !isStreaming && (
            <div className="py-14 text-center">
              <p className="text-mute text-sm mb-4">Try one of these, or ask your own:</p>
              <div className="flex flex-col gap-2 max-w-sm mx-auto">
                {SUGGESTIONS.map(s => (
                  <button key={s} onClick={() => handleSend(s)}
                    className="font-mono text-xs text-left text-paper/70 border border-line-2 rounded px-3 py-2 hover:border-trace hover:text-trace transition-colors">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m) => (
            <motion.div key={m.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
              className={`flex ${m.role === 'human' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] rounded-lg px-3.5 py-2.5 text-sm leading-relaxed ${
                m.role === 'human' ? 'bg-paper text-ink' : 'border border-line-2 text-paper/90'
              }`}>
                {m.role === 'ai' ? <CitationAnswer content={m.content} citations={m.citations || []} /> : m.content}
                {m.cacheHit && <span className="block text-[10px] font-mono text-pulse mt-1.5">⚡ served from cache</span>}
              </div>
            </motion.div>
          ))}

          {messages.filter(m => m.role === 'ai').slice(-1).map(m => <SourcesPanel key={`sources-${m.id}`} citations={m.citations || []} />)}

          {isStreaming && streamingAnswer && (
            <div className="flex justify-start">
              <div className="max-w-[80%] border border-line-2 rounded-lg px-3.5 py-2.5 text-sm text-paper/90 leading-relaxed">
                {streamingAnswer}
                <span className="inline-block w-1.5 h-3.5 bg-trace ml-0.5 type-cursor" />
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="relative panel rounded-lg">
          <input
            value={input} onChange={e => setInput(e.target.value)} onKeyDown={handleKey}
            placeholder="Ask about expenses, invoices, retention policy..."
            className="w-full bg-transparent text-paper placeholder-mute text-sm px-4 py-3.5 pr-12 outline-none font-sans"
          />
          <button onClick={() => handleSend()} disabled={!input.trim() || isStreaming}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 w-8 h-8 rounded bg-paper flex items-center justify-center disabled:opacity-20 hover:bg-trace transition-colors">
            <Send className="w-3.5 h-3.5 text-ink" />
          </button>
        </div>
      </div>
    </div>
  );
}
