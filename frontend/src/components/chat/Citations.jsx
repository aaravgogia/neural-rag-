import { AnimatePresence, motion } from 'framer-motion';
import { BookOpen, ChevronDown, Download, ExternalLink, FileText, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function SourceViewer({ citation, onClose }) {
  const [file, setFile] = useState({ loading: true, url: null, type: '' });
  const page = citation.source_page ? `Page ${citation.source_page}` : 'Relevant passage';

  useEffect(() => {
    if (citation.source_type === 'external' || !citation.doc_id) return undefined;
    let objectUrl;
    axios.get(`${API_URL}/api/v1/documents/${citation.doc_id}/file`, { responseType: 'blob' })
      .then(response => {
        objectUrl = URL.createObjectURL(response.data);
        setFile({ loading: false, url: objectUrl, type: response.headers['content-type'] || response.data.type || '' });
      })
      .catch(() => setFile({ loading: false, url: null, type: '' }));
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [citation]);

  const canEmbedPdf = file.type.includes('pdf');
  return <AnimatePresence><motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 z-50 flex items-center justify-center bg-ink/85 p-4" onClick={onClose}>
    <motion.section initial={{ opacity: 0, scale: .97, y: 12 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: .97, y: 12 }} onClick={event => event.stopPropagation()} className="flex h-[min(84vh,760px)] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-line-2 bg-ink-2 shadow-2xl">
      <header className="flex items-center justify-between border-b border-line px-5 py-3"><div><p className="font-mono text-[10px] tracking-[.16em] text-trace">SOURCE VIEWER · {page.toUpperCase()}</p><h3 className="mt-1 text-sm font-medium text-paper">{citation.doc_title}</h3></div><button type="button" onClick={onClose} className="rounded-md p-2 text-mute hover:bg-line hover:text-paper" aria-label="Close source viewer"><X className="h-4 w-4" /></button></header>
      <div className="border-b border-line bg-trace/5 px-5 py-3"><p className="font-mono text-[10px] text-trace">CITED PASSAGE</p><mark className="mt-1 block bg-transparent text-sm leading-relaxed text-paper">{citation.chunk_text}</mark></div>
      <div className="min-h-0 flex-1 bg-paper/5">{citation.source_type === 'external' ? <a href={citation.url || '#'} target="_blank" rel="noreferrer" className="m-6 inline-flex items-center gap-2 rounded-lg border border-line px-4 py-3 text-sm text-trace"><ExternalLink className="h-4 w-4" />Open external source</a> : file.loading ? <p className="p-6 text-sm text-mute">Loading authorized source file…</p> : canEmbedPdf ? <iframe title={`${citation.doc_title} ${page}`} src={`${file.url}#page=${citation.source_page || 1}`} className="h-full w-full border-0" /> : file.url ? <div className="p-6"><p className="text-sm text-paper">This format cannot be viewed inline. The cited location is {page.toLowerCase()}.</p><a href={file.url} download={citation.doc_title} className="mt-4 inline-flex items-center gap-2 rounded-lg border border-trace/50 bg-trace/10 px-4 py-2 text-sm text-trace"><Download className="h-4 w-4" />Download original</a></div> : <p className="p-6 text-sm text-mute">The original file is no longer available for this older upload.</p>}</div>
    </motion.section>
  </motion.div></AnimatePresence>;
}

function CitationPill({ citation, index, onOpen }) {
  const [open, setOpen] = useState(false);
  return <span className="relative inline-flex align-super ml-0.5"><button type="button" aria-label={`Open source ${index}`} onClick={() => onOpen(citation)} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} className="font-mono text-[10px] leading-none rounded border border-trace/40 bg-trace/10 px-1 py-0.5 text-trace hover:bg-trace hover:text-ink transition-colors">[{index}]</button><AnimatePresence>{open && <motion.div initial={{ opacity: 0, y: 5, scale: .97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 4, scale: .97 }} transition={{ duration: .16 }} className="absolute left-0 bottom-full z-30 mb-2 w-72 rounded-lg border border-line-2 bg-ink-2 p-3 shadow-2xl"><div className="flex items-center gap-1.5 font-mono text-[10px] text-trace"><FileText className="w-3 h-3" />{citation.doc_title}</div><p className="mt-2 text-xs leading-relaxed text-paper/85">{citation.chunk_text}</p><p className="mt-2 font-mono text-[10px] text-mute">{citation.source_page ? `page ${citation.source_page} · ` : ''}chunk {citation.chunk_index + 1}</p></motion.div>}</AnimatePresence></span>;
}

export function CitationAnswer({ content, citations = [] }) {
  const [selected, setSelected] = useState(null);
  const parts = String(content || '').split(/(\[\d+\])/g);
  return <><p className="text-sm leading-relaxed text-paper/90 whitespace-pre-wrap">{parts.map((part, index) => { const match = part.match(/^\[(\d+)\]$/); const citation = match && citations[Number(match[1]) - 1]; return citation ? <CitationPill key={index} citation={citation} index={Number(match[1])} onOpen={setSelected} /> : <span key={index}>{part}</span>; })}</p>{selected && <SourceViewer citation={selected} onClose={() => setSelected(null)} />}</>;
}

export function SourcesPanel({ citations = [] }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(null);
  if (!citations.length) return null;
  return <><div className="mt-3 w-full rounded-lg border border-line bg-ink/40 overflow-hidden"><button onClick={() => setOpen(value => !value)} className="w-full flex items-center justify-between px-3 py-2 text-left"><span className="flex items-center gap-2 font-mono text-[10px] text-mute"><BookOpen className="w-3.5 h-3.5 text-trace" />SOURCES · {citations.length}</span><ChevronDown className={`w-3.5 h-3.5 text-mute transition-transform ${open ? 'rotate-180' : ''}`} /></button><AnimatePresence>{open && <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="border-t border-line"><div className="divide-y divide-line">{citations.map((citation, index) => <button type="button" key={`${citation.doc_id}-${citation.chunk_index}`} onClick={() => setSelected(citation)} className="block w-full p-3 text-left transition-colors hover:bg-trace/5"><div className="flex items-center gap-2 font-mono text-[10px] text-trace"><span>[{index + 1}]</span><span className="truncate">{citation.doc_title}</span><span className="text-mute">{citation.source_page ? `PAGE ${citation.source_page}` : `CHUNK ${citation.chunk_index + 1}`}</span></div><p className="mt-1.5 text-xs leading-relaxed text-paper/80">{citation.chunk_text}</p></button>)}</div></motion.div>}</AnimatePresence></div>{selected && <SourceViewer citation={selected} onClose={() => setSelected(null)} />}</>;
}
