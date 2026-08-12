import { motion, AnimatePresence } from 'framer-motion';
import { useState, useRef, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useChatStore } from '../store/chatStore';
import ReactMarkdown from 'react-markdown';
import Sidebar from '../components/layout/Sidebar';
import { Send, Brain, User, Plus, FileText, BookOpen, Sparkles, Zap, MessageSquare, ArrowDown, ThumbsUp, ThumbsDown } from 'lucide-react';
import toast from 'react-hot-toast';
import { CitationAnswer, SourcesPanel } from '../components/chat/Citations';
import { useSessionPresence } from '../hooks/useSessionPresence';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function TypingIndicator() {
  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }} className="flex items-start gap-3">
      <div className="w-9 h-9 rounded-xl bg-line-2 flex items-center justify-center shrink-0"><Brain className="w-4 h-4 text-paper" /></div>
      <div className="panel rounded-2xl rounded-tl-none px-5 py-4 border border-line">
        <div className="flex items-center gap-3">
          <div className="flex gap-1.5">{[0, 1, 2].map(i => <motion.div key={i} className="w-2.5 h-2.5 rounded-full bg-trace" animate={{ y: [0, -8, 0], opacity: [0.4, 1, 0.4] }} transition={{ duration: 0.8, repeat: Infinity, delay: i * 0.15 }} />)}</div>
          <span className="text-mute text-sm">NeuralRAG is thinking...</span>
        </div>
      </div>
    </motion.div>
  );
}

function MessageBubble({ message, feedbackRating, onFeedback }) {
  const isHuman = message.role === 'human';
  const citations = message.citations || message.sources?.map((source, index) => ({ doc_id: source.document_id || source.id || `source-${index}`, doc_title: source.doc_title || source.source || 'Retrieved source', chunk_text: source.content || source.text || '', source_page: source.source_page || source.page, chunk_index: source.chunk_index ?? index, score: source.score || source.fused_score || 0 })) || [];
  return (
    <motion.div initial={{ opacity: 0, y: 20, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} className={`flex items-start gap-3 ${isHuman ? 'flex-row-reverse' : ''}`}>
      <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${isHuman ? 'from-cyan-500 to-blue-600' : 'bg-line-2'}`}>
        {isHuman ? <User className="w-4 h-4 text-paper" /> : <Brain className="w-4 h-4 text-paper" />}
      </div>
      <div className={`max-w-2xl flex flex-col ${isHuman ? 'items-end' : 'items-start'}`}>
        <div className={`rounded-2xl px-5 py-4 ${isHuman ? 'from-cyan-600/80 to-blue-600/80 rounded-tr-none border border-line-2' : 'panel rounded-tl-none border border-line'}`}>
          {isHuman ? <p className="text-paper text-sm leading-relaxed">{message.content}</p> : citations.length ? <CitationAnswer content={message.content} citations={citations} /> : <div className="prose prose-invert prose-sm max-w-none"><ReactMarkdown>{message.content}</ReactMarkdown></div>}
        </div>
        {!isHuman && <>
          <SourcesPanel citations={citations} />
          <div className="mt-2 flex items-center gap-1.5 font-mono text-[10px] text-mute">
            <span>Was this useful?</span>
            <button type="button" aria-label="Helpful answer" title="Helpful" onClick={() => onFeedback(message.id, 'up')} className={`rounded-md border p-1 transition-colors ${feedbackRating === 'up' ? 'border-trace bg-trace/10 text-trace' : 'border-line text-mute hover:border-trace hover:text-trace'}`}><ThumbsUp className="h-3.5 w-3.5" /></button>
            <button type="button" aria-label="Unhelpful answer" title="Not helpful" onClick={() => onFeedback(message.id, 'down')} className={`rounded-md border p-1 transition-colors ${feedbackRating === 'down' ? 'border-pulse bg-pulse/10 text-pulse' : 'border-line text-mute hover:border-pulse hover:text-pulse'}`}><ThumbsDown className="h-3.5 w-3.5" /></button>
          </div>
        </>}
      </div>
    </motion.div>
  );
}

function PresenceStack({ users }) {
  if (!users.length) return null;
  const visible = users.slice(0, 4);
  return <div className="flex items-center" aria-label={`${users.length} people viewing this chat`}>
    <AnimatePresence initial={false}>
      {visible.map((person, index) => <motion.div key={person.id} initial={{ opacity: 0, scale: .65, x: 8 }} animate={{ opacity: 1, scale: 1, x: 0 }} exit={{ opacity: 0, scale: .65, x: 8 }} transition={{ duration: .18 }} className={`relative flex h-7 w-7 items-center justify-center overflow-hidden rounded-full border-2 border-ink-2 bg-line font-mono text-[9px] text-paper ${index ? '-ml-2' : ''}`} title={`${person.name} is viewing`}>
        {person.avatar ? <img src={person.avatar} alt={person.name} className="h-full w-full object-cover" /> : person.name.slice(0, 1).toUpperCase()}
      </motion.div>)}
    </AnimatePresence>
    {users.length > visible.length && <span className="ml-1.5 font-mono text-[10px] text-mute">+{users.length - visible.length}</span>}
  </div>;
}

const SUGGESTIONS = [
  { icon: '📊', text: 'Summarise key points from my documents' },
  { icon: '🔍', text: 'Find information about a specific topic' },
  { icon: '📝', text: 'Compare different sections of my files' },
  { icon: '💡', text: 'What are the main conclusions?' },
];

export default function ChatPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const { sessions, currentSession, messages, isLoading, createSession, selectSession, sendMessage, fetchSessions } = useChatStore();
  const [input, setInput] = useState('');
  const [useAgent, setUseAgent] = useState(true);
  const [feedbackByMessage, setFeedbackByMessage] = useState({});
  const bottomRef = useRef(null);
  const { users: viewers, typists, notifyTyping } = useSessionPresence(sessionId);

  useEffect(() => { fetchSessions(); }, []);
  useEffect(() => { if (sessionId) selectSession(sessionId); }, [sessionId]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, isLoading]);

  const handleSend = useCallback(async () => {
    const q = input.trim();
    if (!q || isLoading) return;
    let sid = currentSession?.id;
    if (!sid) { const s = await createSession({ title: q.slice(0, 40) }); sid = s.id; navigate(`/chat/${sid}`); }
    setInput('');
    notifyTyping('');
    try { await sendMessage(q, useAgent); } catch (error) {
      if (error.response?.status === 402) {
        const detail = error.response.data?.detail;
        toast.error(`${detail?.message || 'Workspace quota reached.'} ${detail?.usage?.tokens ?? 0}/${detail?.limit?.tokens ?? 0} tokens used.`);
      } else if (error.response?.status === 429) {
        const retryAfter = error.response.headers?.['retry-after'];
        toast.error(`You’ve reached the message limit. Try again${retryAfter ? ` in ${retryAfter}s` : ' shortly'}.`);
      } else toast.error('Failed to send message.');
    }
  }, [input, isLoading, currentSession, useAgent, notifyTyping]);

  const handleKey = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } };
  const handleFeedback = useCallback(async (messageId, rating) => {
    if (!currentSession?.id) return;
    const previous = feedbackByMessage[messageId];
    setFeedbackByMessage(state => ({ ...state, [messageId]: rating }));
    try {
      await axios.post(`${API_URL}/api/v1/feedback`, { message_id: messageId, session_id: currentSession.id, rating });
      toast.success(rating === 'up' ? 'Thanks for the feedback.' : 'Thanks — we’ll review this answer.');
    } catch (error) {
      setFeedbackByMessage(state => ({ ...state, [messageId]: previous }));
      toast.error('Could not save feedback. Please try again.');
    }
  }, [currentSession?.id, feedbackByMessage]);
  const isEmpty = messages.length === 0;

  return (
    <div className="flex h-screen bg-ink overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="panel border-b border-line px-6 py-3 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-line flex items-center justify-center"><MessageSquare className="w-4 h-4 text-trace" /></div>
            <h2 className="text-paper font-semibold text-sm">{currentSession?.title || 'New Conversation'}</h2>
          </div>
          <div className="flex items-center gap-3">
            <PresenceStack users={viewers} />
            <div className="flex items-center gap-2 panel px-3 py-1.5 rounded-xl border border-line">
              <Zap className={`w-3.5 h-3.5 ${useAgent ? 'text-trace' : 'text-mute'}`} />
              <span className="text-xs text-mute">Agent</span>
              <button onClick={() => setUseAgent(v => !v)} className={`relative w-9 h-5 rounded-full ${useAgent ? 'bg-paper' : 'bg-gray-700'}`}>
                <motion.div animate={{ x: useAgent ? 16 : 2 }} className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow" />
              </button>
            </div>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-8">
          {isEmpty ? (
            <div className="flex flex-col items-center justify-center h-full min-h-[60vh] text-center">
              <div className="w-24 h-24 rounded-3xl bg-line-2 flex items-center justify-center shadow-2xl mb-6"><Brain className="w-12 h-12 text-paper" /></div>
              <h2 className="text-3xl font-black text-paper mb-2">Ask <span className="">anything</span></h2>
              <p className="text-mute text-base mb-10 max-w-md">Upload documents, then ask questions.</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-lg">
                {SUGGESTIONS.map((s, i) => (
                  <button key={i} onClick={() => setInput(s.text)} className="flex items-center gap-3 px-4 py-3 panel rounded-2xl border border-line text-left text-paper/80 text-sm">
                    <span className="text-xl">{s.icon}</span><span>{s.text}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>{messages.map((msg) => <MessageBubble key={msg.id} message={msg} feedbackRating={feedbackByMessage[msg.id]} onFeedback={handleFeedback} />)}{isLoading && <TypingIndicator />}</>
          )}
          <div ref={bottomRef} />
        </div>
        <div className="px-6 pb-6 pt-3 border-t border-line">
          <AnimatePresence>{typists.length > 0 && <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 4 }} className="mb-2 flex items-center gap-2 font-mono text-[10px] text-mute"><span className="w-1.5 h-1.5 rounded-full bg-pulse animate-pulse" />{typists.map(person => person.name).join(', ')} {typists.length === 1 ? 'is' : 'are'} typing</motion.div>}</AnimatePresence>
          <div className="relative panel rounded-2xl border border-line">
            <Sparkles className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-trace/60" />
            <textarea value={input} onChange={e => { setInput(e.target.value); notifyTyping(e.target.value); }} onKeyDown={handleKey}
              placeholder="Ask a question about your documents..." rows={1}
              className="w-full bg-transparent text-paper placeholder-gray-500 text-sm resize-none pl-11 pr-14 py-4 outline-none leading-relaxed max-h-40 overflow-y-auto" />
            <button onClick={handleSend} disabled={!input.trim() || isLoading}
              className="absolute right-3 top-1/2 -translate-y-1/2 w-9 h-9 rounded-xl bg-paper flex items-center justify-center disabled:opacity-30">
              <Send className="w-4 h-4 text-paper" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
