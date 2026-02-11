import React, { useState } from 'react';
import { X, ChevronRight } from 'lucide-react';
import { useLocale } from '../i18n/context';

interface TimelineArticle {
  id: number;
  ticker: string;
  title: string;
  summary?: string;
  url?: string;
  source?: string;
  published_at?: string;
  relation_type?: string;
}

interface TimelineMonth {
  month: string;
  articles: TimelineArticle[];
}

interface LongStoryTimelineProps {
  loading: boolean;
  title: string;
  summary: string;
  theme: string;
  timeline: TimelineMonth[] | null;
  onClose: () => void;
  formatTimestamp: (iso: string) => string;
}

const LongStoryTimeline: React.FC<LongStoryTimelineProps> = ({
  loading,
  title,
  summary,
  theme,
  timeline,
  onClose,
  formatTimestamp,
}) => {
  const { t } = useLocale();
  const [expandedArticleId, setExpandedArticleId] = useState<number | null>(null);

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="p-4 border-b border-gray-900 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest" style={{ backgroundColor: 'rgba(204, 255, 0, 0.15)', color: '#CCFF00' }}>{t('stockDetail.longStory')}</span>
        </div>
        <button onClick={onClose} className="p-1.5 hover:bg-gray-800 rounded-full transition-colors text-gray-500 hover:text-white">
          <X size={18} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 sm:p-6 md:p-8 space-y-10 scrollbar-hide min-h-0">
        {loading && (
          <p className="text-[11px] text-gray-500 italic">{t('stockDetail.loadingTimeline')}</p>
        )}
        {!loading && (
          <>
            <h2 className="text-2xl font-black leading-tight text-white">{title}</h2>
            {theme && (
              <section>
                <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">Theme</h3>
                <div className="p-5 bg-[#0c0c0c] border border-gray-900 rounded-xl">
                  <p className="text-gray-400 text-sm leading-relaxed">{theme}</p>
                </div>
              </section>
            )}
            {summary && (
              <section>
                <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('stockDetail.summary')}</h3>
                <div className="p-5 bg-[#0c0c0c] border border-gray-900 rounded-xl">
                  <p className="text-gray-400 text-sm leading-relaxed whitespace-pre-wrap">{summary}</p>
                </div>
              </section>
            )}
            {timeline && timeline.length === 0 && (
              <p className="text-[11px] text-gray-500 italic">{t('stockDetail.noTimelineData')}</p>
            )}
            {timeline && timeline.length > 0 && (
              <section>
                <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('stockDetail.supportingArticles')}</h3>
                <div className="space-y-10">
                  {timeline.map((m) => (
                    <div key={m.month}>
                      <h4 className="text-[9px] font-black uppercase text-[#CCFF00] tracking-[0.2em] mb-3">{m.month}</h4>
                      <div className="space-y-8">
                        {m.articles.map((a) => {
                          const isExpanded = expandedArticleId === a.id;
                          const hasSummary = !!a.summary?.trim();
                          return (
                            <div key={a.id} className="relative flex items-start group">
                              <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight transition-colors group-hover:text-gray-400">
                                {a.published_at ? formatTimestamp(a.published_at) : '\u2014'}
                              </div>
                              <div className="absolute left-[110px] top-2 -translate-x-1/2 w-2.5 h-2.5 rounded-full border border-black z-10 bg-gray-600 group-hover:bg-[#CCFF00] transition-all" />
                              <div className="flex-1 pl-4 md:pl-12 pr-4">
                                <div className="p-4 bg-[#0c0c0c] border border-gray-900 rounded-xl hover:border-gray-700 transition-all flex items-start gap-3">
                                  <button
                                    type="button"
                                    onClick={() => setExpandedArticleId((id) => (id === a.id ? null : a.id))}
                                    className="flex-shrink-0 p-0.5 rounded hover:bg-gray-800 text-gray-700 group-hover:text-[#CCFF00] transition-all"
                                    title={hasSummary ? (isExpanded ? t('stockDetail.hideSummary') : t('stockDetail.showSummary')) : t('stockDetail.noSummary')}
                                    disabled={!hasSummary}
                                  >
                                    <ChevronRight size={14} className={`mt-0.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                                  </button>
                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center justify-between gap-2 mb-1">
                                      <span className="text-[8px] font-black text-gray-600 uppercase">{a.source ?? 'Unknown'}</span>
                                      {a.relation_type ? (
                                        <span className="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-wider bg-gray-800 text-gray-400 flex-shrink-0">
                                          {a.relation_type.replace(/_/g, ' ')}
                                        </span>
                                      ) : null}
                                    </div>
                                    <h4 className="text-[11px] font-bold text-gray-400 group-hover:text-white leading-tight">{a.title}</h4>
                                    {hasSummary && isExpanded && (
                                      <>
                                        <p className="mt-3 text-[11px] text-gray-500 leading-relaxed border-t border-gray-800 pt-3">
                                          {a.summary}
                                        </p>
                                        {a.url && (
                                          <a
                                            href={a.url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            onClick={(e) => e.stopPropagation()}
                                            className="mt-3 inline-block text-[#CCFF00] hover:underline text-[11px] font-medium"
                                          >
                                            {t('stockDetail.viewOriginal')} →
                                          </a>
                                        )}
                                      </>
                                    )}
                                  </div>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default LongStoryTimeline;
