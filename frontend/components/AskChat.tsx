import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, Send, ExternalLink, Trash2 } from 'lucide-react';
import { useLocale } from '../i18n';
import { API_BASE } from '../api';

const CUSTOM_STORY_MAX_CHARS = 200;
const ASK_COOLDOWN_SECONDS = 5;

interface CustomStoryResult {
  answer: string;
  articles: Array<{ id: number; ticker: string; title: string; summary?: string; url?: string; source?: string; published_at?: string }>;
  context_type?: string;
  macro_sources?: Array<{ topic: string; title?: string; as_of_date?: string }>;
  detected_tickers?: string[];
}

type AskMessage = {
  role: 'user' | 'assistant';
  content: string;
  articles?: CustomStoryResult['articles'];
  contextType?: string;
  detectedTickers?: string[];
};

const AskChat: React.FC = () => {
  const { t } = useLocale();
  const [askQuestion, setAskQuestion] = useState('');
  const [askMessages, setAskMessages] = useState<AskMessage[]>([]);
  const [askLoading, setAskLoading] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const [askCooldownRemaining, setAskCooldownRemaining] = useState(0);
  const askChatScrollRef = useRef<HTMLDivElement>(null);

  // Cooldown timer
  useEffect(() => {
    if (askCooldownRemaining <= 0) return;
    const t = setInterval(() => {
      setAskCooldownRemaining((s) => (s <= 1 ? 0 : s - 1));
    }, 1000);
    return () => clearInterval(t);
  }, [askCooldownRemaining]);

  // Scroll to bottom on new messages
  useEffect(() => {
    askChatScrollRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [askMessages, askLoading]);

  const handleSubmit = () => {
    const question = askQuestion.trim();
    if (!question) return;
    if (question.length > CUSTOM_STORY_MAX_CHARS) {
      setAskError(t('ask.maxChars', { max: CUSTOM_STORY_MAX_CHARS }));
      return;
    }
    setAskError(null);
    setAskQuestion('');
    setAskMessages((prev) => [...prev, { role: 'user', content: question }]);
    setAskLoading(true);
    const history = askMessages.slice(-6).map((m) => ({ role: m.role, content: m.content }));
    fetch(`${API_BASE}/storylines/custom`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, history }),
    })
      .then(async (res) => {
        if (res.status === 429) {
          const retryAfter = res.headers.get('Retry-After');
          const secs = retryAfter ? Math.min(parseInt(retryAfter, 10) || 60, 120) : 60;
          let detail = 'Too many requests; please wait a minute before asking again.';
          try {
            const d = await res.json() as { detail?: string };
            if (d.detail) detail = d.detail;
          } catch {
            // ignore
          }
          setAskError(detail);
          setAskCooldownRemaining(secs);
          throw new Error(detail);
        }
        if (!res.ok) return res.json().then((d: { detail?: string }) => Promise.reject(new Error(d.detail ?? res.statusText)));
        return res.json();
      })
      .then((data: CustomStoryResult) => {
        setAskMessages((prev) => [...prev, {
          role: 'assistant',
          content: data.answer,
          articles: data.articles,
          contextType: data.context_type,
          detectedTickers: data.detected_tickers,
        }]);
        setAskCooldownRemaining(ASK_COOLDOWN_SECONDS);
      })
      .catch((err: Error) => {
        setAskMessages((prev) => [...prev, { role: 'assistant', content: err.message || 'Failed to generate answer.', articles: [], contextType: undefined, detectedTickers: undefined }]);
        setAskError(err.message || 'Failed to generate answer.');
        const isRateLimit = /too many|daily limit/i.test(err.message || '');
        if (!isRateLimit) setAskCooldownRemaining(ASK_COOLDOWN_SECONDS);
      })
      .finally(() => setAskLoading(false));
  };

  const handleClearChat = () => {
    setAskMessages([]);
    setAskError(null);
  };

  return (
    <div className="flex flex-col h-full min-h-0 bg-black">
      {/* Top bar */}
      <div className="flex-shrink-0 px-4 sm:px-6 py-3 border-b border-gray-800 flex items-center justify-between">
        <p className="text-xs text-gray-500">{t('ask.topBarHint')}</p>
        {askMessages.length > 0 && (
          <button type="button" onClick={handleClearChat} className="text-xs font-medium text-gray-500 hover:text-gray-300 flex items-center gap-1.5" aria-label="Clear chat">
            <Trash2 size={14} /> Clear chat
          </button>
        )}
      </div>

      {/* Scrollable message area */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6">
          {askMessages.length === 0 && !askLoading && (
            <div className="flex flex-col items-center justify-center py-16 sm:py-24 text-center">
              <div className="w-12 h-12 rounded-full bg-gray-800 flex items-center justify-center mb-4">
                <MessageSquare size={24} className="text-[#CCFF00]" />
              </div>
              <p className="text-lg font-medium text-gray-300 mb-1">{t('ask.emptyTitle')}</p>
              <p className="text-sm text-gray-500 max-w-sm">{t('ask.emptyDescription')}</p>
            </div>
          )}
          {askMessages.map((msg, idx) => (
            <div key={idx} className={`flex w-full mb-6 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] sm:max-w-[80%] ${msg.role === 'user' ? 'order-2' : ''}`}>
                {msg.role === 'user' ? (
                  <div className="rounded-2xl rounded-br-md px-4 py-3 bg-[#CCFF00]/20 text-sm text-gray-100 leading-relaxed">
                    {msg.content}
                  </div>
                ) : (
                  <div className="rounded-2xl rounded-bl-md px-4 py-3 bg-gray-800/80 text-sm text-gray-200 leading-relaxed">
                    {(msg.contextType === 'macro' || (msg.detectedTickers && msg.detectedTickers.length > 0)) && (
                      <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">
                        Context: {msg.contextType === 'macro' ? 'Macro' : (msg.detectedTickers || []).join(', ')}
                      </p>
                    )}
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                    {msg.articles && msg.articles.length > 0 && (
                      <div className="mt-4 pt-3 border-t border-gray-700">
                        <p className="text-[10px] font-bold text-gray-500 uppercase tracking-wider mb-2">{t('ask.articles')} ({msg.articles.length})</p>
                        <ul className="space-y-2">
                          {msg.articles.map((a) => {
                            const articleDateStr = a.published_at
                              ? (() => {
                                  try {
                                    const d = new Date(a.published_at);
                                    return isNaN(d.getTime()) ? null : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
                                  } catch {
                                    return null;
                                  }
                                })()
                              : null;
                            return (
                            <li key={`${idx}-${a.id}`} className="flex flex-col gap-0.5">
                              {a.url ? (
                                <a
                                  href={a.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="block rounded-lg px-3 py-2 -mx-1 hover:bg-gray-700/50 transition-colors cursor-pointer group border border-transparent hover:border-gray-600"
                                >
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span className="flex-1 min-w-0 text-[13px] font-medium text-[#CCFF00] group-hover:underline truncate">{a.title}</span>
                                    <ExternalLink size={12} className="flex-shrink-0 text-[#CCFF00]/80" aria-hidden />
                                    <span className="text-[10px] font-medium text-gray-600 uppercase flex-shrink-0">
                                      {articleDateStr ? `${articleDateStr} · ` : ''}{a.source ?? t('ask.unknown')}
                                    </span>
                                  </div>
                                  {a.summary && <p className="text-xs text-gray-500 line-clamp-2 mt-0.5">{a.summary}</p>}
                                </a>
                              ) : (
                                <div className="rounded-lg px-3 py-2 border border-transparent opacity-80">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span className="flex-1 min-w-0 text-[13px] font-medium text-gray-400 truncate">{a.title}</span>
                                    <span className="text-[10px] font-medium text-gray-600 uppercase flex-shrink-0">
                                      {articleDateStr ? `${articleDateStr} · ` : ''}{a.source ?? t('ask.unknown')}
                                    </span>
                                  </div>
                                  {a.summary && <p className="text-xs text-gray-500 line-clamp-2 mt-0.5">{a.summary}</p>}
                                </div>
                              )}
                            </li>
                            );
                          })}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
          {askLoading && (
            <div className="flex justify-start mb-6">
              <div className="rounded-2xl rounded-bl-md px-4 py-3 bg-gray-800/80 text-sm text-gray-500">Generating…</div>
            </div>
          )}
          <div ref={askChatScrollRef} />
        </div>
      </div>

      {/* Bottom input bar */}
      <div className="flex-shrink-0 p-4 sm:p-6 border-t border-gray-800 bg-black">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-end gap-2 rounded-2xl border border-gray-700 bg-gray-900/80 px-4 py-2 focus-within:border-[#CCFF00]/50 transition-colors">
            <input
              type="text"
              value={askQuestion}
              onChange={(e) => { setAskQuestion(e.target.value.slice(0, CUSTOM_STORY_MAX_CHARS)); setAskError(null); }}
              placeholder={t('ask.placeholderQuestion')}
              maxLength={CUSTOM_STORY_MAX_CHARS}
              className="flex-1 min-w-0 py-3 bg-transparent text-sm text-gray-200 placeholder-gray-500 outline-none"
              disabled={askLoading}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); handleSubmit(); } }}
            />
            <button
              type="button"
              onClick={handleSubmit}
              disabled={askLoading || askCooldownRemaining > 0 || !askQuestion.trim()}
              className="flex-shrink-0 p-2.5 rounded-xl bg-[#CCFF00] text-black hover:bg-[#b8e600] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              aria-label={t('ask.askButton')}
            >
              <Send size={18} />
            </button>
          </div>
          <div className="flex items-center justify-between mt-2 px-1 flex-wrap gap-y-1">
            <span className="text-[10px] text-gray-600">{askQuestion.length}/{CUSTOM_STORY_MAX_CHARS}</span>
            <span className="text-[10px] text-gray-500">{t('ask.sendHint')}</span>
            {askError && <p className="text-xs text-amber-500 truncate max-w-[70%] w-full order-last">{askError}</p>}
            {askCooldownRemaining > 0 && <span className="text-[10px] text-gray-500">{t('ask.waitSeconds', { seconds: askCooldownRemaining })}</span>}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AskChat;
