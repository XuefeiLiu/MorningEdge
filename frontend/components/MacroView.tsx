import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Calendar, X, ArrowLeft } from 'lucide-react';
import { useLocale } from '../i18n';
import { API_BASE } from '../api';

/** Backend topic ids; labels come from i18n (macro.fx, macro.rates, etc.) */
const TOPIC_IDS = ['FX', 'RATE', 'CREDIT', 'COMMODITY', 'EQUITY', 'Fiscal Policy', 'Monetary Policy', 'Trump'] as const;
const TOPIC_LABEL_KEYS: Record<string, string> = {
  'FX': 'macro.fx',
  'RATE': 'macro.rates',
  'CREDIT': 'macro.credit',
  'COMMODITY': 'macro.commodity',
  'EQUITY': 'macro.equity',
  'Fiscal Policy': 'macro.fiscal',
  'Monetary Policy': 'macro.monetary',
  'Trump': 'macro.trump',
};

type MacroSubTab = 'summary' | 'FX' | 'RATE' | 'CREDIT' | 'COMMODITY' | 'EQUITY' | 'Fiscal Policy' | 'Monetary Policy' | 'Trump';

interface BriefListItem {
  topic: string | null;
  title: string | null;
  summary: string | null;
}

interface BriefFull {
  topic?: string | null;
  title?: string | null;
  summary?: string | null;
  summary_bullets?: string[] | null;
  article_bullets?: string[] | null;
  sources?: unknown;
  [key: string]: unknown;
}

interface PastWeekItem {
  as_of_date: string;
  title: string | null;
  summary: string | null;
  topic: string;
  coverage_gap?: boolean;
}

/** Daily summary of summaries (LLM-synthesized from all 8 topic briefs). */
interface DailySummaryItem {
  as_of_date: string;
  title: string | null;
  summary: string | null;
  summary_bullets?: string[] | null;
}

function todayISO(): string {
  const d = new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

const VALID_TOPIC_IDS = new Set<string>(TOPIC_IDS);

function buildBriefUrl(date: string, topic: string): string {
  const base = typeof window !== 'undefined' ? window.location.origin + window.location.pathname : '';
  const params = new URLSearchParams({ tab: 'macro', date, topic });
  return `${base}?${params.toString()}`;
}

/** Clean related-article display text: no "...", no "[]" (keep content inside brackets). */
function cleanLinkText(text: string): string {
  if (!text || typeof text !== 'string') return text ?? '';
  let s = text.replace(/\.\.\.|…/g, ' ').trim();
  s = s.replace(/\[([^\]]*)\]/g, '$1').trim();
  return s.replace(/\s+/g, ' ');
}

type ArticleBlock =
  | { type: 'paragraph'; text: string }
  | { type: 'table'; header: string; columns: string[]; dataRows: string[][] }
  | { type: 'kv'; header: string; rows: { key: string; value: string }[]; shortEnough: boolean }
  | { type: 'label'; subTitle: string; content: string }
  | { type: 'links'; header: string; links: { title: string; url: string }[] }
  | { type: 'bullet_links'; header: string; items: { text: string; url: string }[] };
type ArticleLink = { title: string; url: string };

/** Parse article_bullets into blocks. Link sections (Related news articles) become a 'links' block; paragraphs and sub-tables are not clickable. */
function parseArticleBullets(bullets: string[]): { blocks: ArticleBlock[] } {
  const blocks: ArticleBlock[] = [];
  let i = 0;
  while (i < bullets.length) {
    const raw = typeof bullets[i] === 'string' ? (bullets[i] as string).replace(/^\s*[•\-]\s*/, '').trim() : String(bullets[i]);
    const isHeader = raw.endsWith(':') && !raw.startsWith('  ');
    const nextRaw = i + 1 < bullets.length ? String(bullets[i + 1]).trim() : '';
    const isNestedTable = isHeader && nextRaw.startsWith('__TBL__\t');
    if (isNestedTable && i + 1 < bullets.length) {
      const colLine = String(bullets[i + 1]).trim();
      const parts = colLine.split('\t');
      const columns = parts[0] === '__TBL__' ? parts.slice(1) : parts;
      const dataRows: string[][] = [];
      let j = i + 2;
      while (j < bullets.length) {
        const rowLine = String(bullets[j]);
        if (!rowLine.startsWith('  ') || rowLine.indexOf('\t') === -1) break;
        const cells = rowLine.trim().split('\t');
        if (cells.length >= 1) dataRows.push(cells);
        j++;
      }
      blocks.push({ type: 'table', header: raw.slice(0, -1), columns, dataRows });
      i = j;
      continue;
    }
    const kvRows: { key: string; value: string }[] = [];
    if (isHeader && i + 1 < bullets.length) {
      let j = i + 1;
      while (j < bullets.length) {
        const line = typeof bullets[j] === 'string' ? (bullets[j] as string).replace(/^\s*[•\-]\s*/, '').trim() : String(bullets[j]);
        const twoSpaces = (bullets[j] as string).startsWith('  ');
        const colonIdx = line.indexOf(': ');
        if (twoSpaces && colonIdx > 0 && !line.startsWith('__TBL__') && !line.startsWith('__LINK__\t') && !line.startsWith('__BULLET_LINK__\t')) {
          kvRows.push({ key: line.slice(0, colonIdx).trim(), value: line.slice(colonIdx + 2).trim() });
          j++;
        } else break;
      }
    }
    const bulletLinkRows: { text: string; url: string }[] = [];
    if (isHeader && i + 1 < bullets.length) {
      let j = i + 1;
      while (j < bullets.length) {
        const rowLine = String(bullets[j]);
        if (!rowLine.startsWith('  ') || rowLine.indexOf('__BULLET_LINK__\t') === -1) break;
        const parts = rowLine.trim().split('\t');
        if (parts[0] === '__BULLET_LINK__' && parts.length >= 2) {
          bulletLinkRows.push({ text: parts[1] ?? '', url: parts[2] ?? '' });
          j++;
        } else break;
      }
    }
    if (bulletLinkRows.length > 0) {
      blocks.push({ type: 'bullet_links', header: raw.slice(0, -1), items: bulletLinkRows });
      i += 1 + bulletLinkRows.length;
      continue;
    }
    const linkRows: { title: string; url: string }[] = [];
    if (isHeader && i + 1 < bullets.length) {
      let j = i + 1;
      while (j < bullets.length) {
        const rowLine = String(bullets[j]);
        if (!rowLine.startsWith('  ') || rowLine.indexOf('__LINK__\t') === -1) break;
        const parts = rowLine.trim().split('\t');
        if (parts[0] === '__LINK__' && parts.length >= 2) {
          linkRows.push({ title: parts[1] ?? '', url: parts[2] ?? '' });
          j++;
        } else break;
      }
    }
    if (linkRows.length > 0) {
      const header = raw.slice(0, -1);
      blocks.push({ type: 'links', header, links: linkRows });
      i += 1 + linkRows.length;
      continue;
    }
    if (kvRows.length > 0) {
      const header = raw.slice(0, -1);
      const shortEnough = kvRows.length <= 12 && kvRows.every(r => r.value.length <= 320);
      blocks.push({ type: 'kv', header, rows: kvRows, shortEnough });
      i += 1 + kvRows.length;
      continue;
    }
    const colonIdx = raw.indexOf(': ');
    const isLabelContent = colonIdx > 0 && colonIdx < 60 && !raw.startsWith('  ');
    if (isLabelContent) {
      blocks.push({ type: 'label', subTitle: raw.slice(0, colonIdx).trim(), content: raw.slice(colonIdx + 2).trim() });
      i++;
      continue;
    }
    blocks.push({ type: 'paragraph', text: raw });
    i++;
  }
  return { blocks };
}

const MacroView: React.FC = () => {
  const { t } = useLocale();
  const dateInputRef = useRef<HTMLInputElement>(null);
  const [dateStr, setDateStr] = useState<string>(todayISO);
  const [subTab, setSubTab] = useState<MacroSubTab>('summary');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const [summaryList, setSummaryList] = useState<BriefListItem[] | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [dailySummary, setDailySummary] = useState<DailySummaryItem | null>(null);
  const [dailySummaryLoading, setDailySummaryLoading] = useState(false);

  const [topicBrief, setTopicBrief] = useState<BriefFull | null>(null);
  const [topicLoading, setTopicLoading] = useState(false);
  const [topicError, setTopicError] = useState<string | null>(null);

  const [pastWeekList, setPastWeekList] = useState<PastWeekItem[] | null>(null);
  const [pastWeekLoading, setPastWeekLoading] = useState(false);
  /** When set, show this date's full brief on the right (topic sub-tab only). Cleared when switching topic. */
  const [selectedBriefDate, setSelectedBriefDate] = useState<string | null>(null);

  // Sync date and topic from URL on mount (e.g. opened from new-tab link); open brief on right when topic is set
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const dateParam = params.get('date');
    const topicParam = params.get('topic');
    if (dateParam && /^\d{4}-\d{2}-\d{2}$/.test(dateParam)) setDateStr(dateParam);
    if (topicParam && VALID_TOPIC_IDS.has(topicParam)) {
      setSubTab(topicParam as MacroSubTab);
      if (dateParam && /^\d{4}-\d{2}-\d{2}$/.test(dateParam)) setSelectedBriefDate(dateParam);
    }
  }, []);

  const fetchSummary = useCallback(async () => {
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const res = await fetch(`${API_BASE}/macro/briefs?date=${encodeURIComponent(dateStr)}`);
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }
      const data = await res.json();
      setSummaryList(Array.isArray(data) ? data : []);
    } catch (e) {
      setSummaryList([]);
      setSummaryError(e instanceof Error ? e.message : 'Failed to load briefs');
    } finally {
      setSummaryLoading(false);
    }
  }, [dateStr]);

  const fetchDailySummary = useCallback(async () => {
    setDailySummaryLoading(true);
    setDailySummary(null);
    try {
      const res = await fetch(`${API_BASE}/macro/daily-summary?date=${encodeURIComponent(dateStr)}`);
      if (res.status === 404) {
        setDailySummary(null);
        return;
      }
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }
      const data = await res.json();
      setDailySummary(data);
    } catch {
      setDailySummary(null);
    } finally {
      setDailySummaryLoading(false);
    }
  }, [dateStr]);

  const fetchPastWeek = useCallback(async (topic: string) => {
    setPastWeekLoading(true);
    setPastWeekList(null);
    try {
      const res = await fetch(
        `${API_BASE}/macro/briefs?topic=${encodeURIComponent(topic)}&range=week`
      );
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }
      const data = await res.json();
      setPastWeekList(Array.isArray(data) ? data : []);
    } catch {
      setPastWeekList([]);
    } finally {
      setPastWeekLoading(false);
    }
  }, []);

  useEffect(() => {
    if (subTab === 'summary') fetchDailySummary();
  }, [subTab, dateStr, fetchDailySummary]);

  const fetchTopicBriefForDate = useCallback(async (date: string, topic: string) => {
    setTopicLoading(true);
    setTopicError(null);
    try {
      const res = await fetch(
        `${API_BASE}/macro/briefs?date=${encodeURIComponent(date)}&topic=${encodeURIComponent(topic)}`
      );
      if (res.status === 404) {
        setTopicBrief(null);
        setTopicError(`No brief for this topic on ${date}`);
        return;
      }
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || res.statusText);
      }
      const data = await res.json();
      setTopicBrief(data);
    } catch (e) {
      setTopicBrief(null);
      setTopicError(e instanceof Error ? e.message : 'Failed to load brief');
    } finally {
      setTopicLoading(false);
    }
  }, []);

  // When user has clicked a past-week card (selectedBriefDate), fetch that date's full brief for the right panel
  useEffect(() => {
    if (subTab === 'summary' || !selectedBriefDate) return;
    fetchTopicBriefForDate(selectedBriefDate, subTab);
  }, [subTab, selectedBriefDate, fetchTopicBriefForDate]);

  useEffect(() => {
    if (subTab !== 'summary') fetchPastWeek(subTab);
  }, [subTab, fetchPastWeek]);

  // Only show past-week items that have real coverage (hide limited-coverage / no-article dates)
  const pastWeekWithCoverage = React.useMemo(() => {
    if (!pastWeekList || pastWeekList.length === 0) return [];
    return pastWeekList.filter((item) => item.coverage_gap !== true);
  }, [pastWeekList]);

  // On desktop only: open the first article by default when on a topic sub-tab. On mobile show title page first (no auto-select).
  useEffect(() => {
    if (subTab === 'summary' || pastWeekWithCoverage.length === 0) return;
    const isDesktop = typeof window !== 'undefined' && window.innerWidth >= 768;
    if (selectedBriefDate == null && isDesktop) {
      const first = pastWeekWithCoverage[0];
      const date = typeof first.as_of_date === 'string' ? first.as_of_date : String(first.as_of_date);
      setSelectedBriefDate(date);
    } else if (selectedBriefDate != null) {
      // If current selection is not in list (e.g. coverage changed), switch to first with coverage on desktop; on mobile clear so title page shows
      const hasSelection = pastWeekWithCoverage.some((item) => {
        const d = typeof item.as_of_date === 'string' ? item.as_of_date : String(item.as_of_date);
        return d === selectedBriefDate;
      });
      if (!hasSelection) {
        if (isDesktop) {
          const first = pastWeekWithCoverage[0];
          setSelectedBriefDate(typeof first.as_of_date === 'string' ? first.as_of_date : String(first.as_of_date));
        } else {
          setSelectedBriefDate(null);
        }
      }
    }
  }, [subTab, pastWeekWithCoverage, selectedBriefDate]);

  const prevSubTabRef = useRef<MacroSubTab>('summary');
  // When switching from one topic to another, clear right-panel selection (keep selection when landing from Summary or from URL)
  useEffect(() => {
    const prev = prevSubTabRef.current;
    prevSubTabRef.current = subTab;
    if (subTab !== 'summary' && prev !== 'summary' && prev !== subTab) {
      setSelectedBriefDate(null);
      setTopicBrief(null);
      setTopicError(null);
    }
  }, [subTab]);

  const topicLabel = (id: string) => {
    const key = TOPIC_LABEL_KEYS[id];
    return key ? t(key) : id;
  };

  const handleCloseMacroDetail = () => {
    setSelectedBriefDate(null);
    setTopicBrief(null);
    setTopicError(null);
  };

  const hasMacroDetail = subTab !== 'summary' && selectedBriefDate != null;

  const handleNavClick = (tab: MacroSubTab) => {
    setSubTab(tab);
    setMobileMenuOpen(false);
  };

  return (
    <div className="w-full h-full flex relative">
      {/* Mobile Menu Toggle Button - only show when not in article detail */}
      {!hasMacroDetail && (
        <button
          onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          className="md:hidden fixed bottom-6 right-6 z-50 bg-[#CCFF00] text-black p-3 rounded-full shadow-lg hover:bg-[#b3e600] transition-colors"
          aria-label="Toggle menu"
        >
          {mobileMenuOpen ? <X size={24} /> : <Calendar size={24} />}
        </button>
      )}

      {/* Left Sidebar Navigation */}
      <div className={`
        ${hasMacroDetail ? 'hidden md:block' : mobileMenuOpen ? 'block' : 'hidden md:block'}
        ${mobileMenuOpen ? 'fixed inset-0 z-40 md:relative' : ''}
        w-full md:w-60 flex-shrink-0 bg-[#0a0a0a] border-r border-gray-800 p-6 overflow-y-auto
      `}>
        <div className="space-y-6">
          {/* OVERVIEW Section */}
          <div>
            <h4 className="text-[10px] font-bold uppercase text-gray-500 tracking-wider mb-2">
              {t('macro.overview')}
            </h4>
            <button
              onClick={() => handleNavClick('summary')}
              className={`w-full text-left px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                subTab === 'summary' 
                  ? 'bg-[#CCFF00] text-black' 
                  : 'text-gray-400 hover:bg-gray-800 hover:text-white'
              }`}
            >
              {t('macro.summary')}
            </button>
          </div>

          {/* MARKETS Section */}
          <div>
            <h4 className="text-[10px] font-bold uppercase text-gray-500 tracking-wider mb-2">
              {t('macro.markets')}
            </h4>
            <div className="space-y-1">
              {(['FX', 'RATE', 'CREDIT', 'COMMODITY', 'EQUITY'] as const).map((id) => (
                <button
                  key={id}
                  onClick={() => handleNavClick(id as MacroSubTab)}
                  className={`w-full text-left px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                    subTab === id 
                      ? 'bg-[#CCFF00] text-black' 
                      : 'text-gray-400 hover:bg-gray-800 hover:text-white'
                  }`}
                >
                  {topicLabel(id)}
                </button>
              ))}
            </div>
          </div>

          {/* POLICY Section */}
          <div>
            <h4 className="text-[10px] font-bold uppercase text-gray-500 tracking-wider mb-2">
              {t('macro.policy')}
            </h4>
            <div className="space-y-1">
              {(['Fiscal Policy', 'Monetary Policy', 'Trump'] as const).map((id) => (
                <button
                  key={id}
                  onClick={() => handleNavClick(id as MacroSubTab)}
                  className={`w-full text-left px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                    subTab === id 
                      ? 'bg-[#CCFF00] text-black' 
                      : 'text-gray-400 hover:bg-gray-800 hover:text-white'
                  }`}
                >
                  {topicLabel(id)}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Right Content Area */}
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Header with Date Picker - hide on mobile when article detail is open */}
        <div className={`flex items-center justify-between gap-4 p-4 sm:p-6 border-b border-gray-900 ${hasMacroDetail ? 'hidden md:flex' : 'flex'}`}>
          <h3 className="text-[10px] font-black uppercase text-[#CCFF00] tracking-[0.2em]">
            {t('macro.title')}
          </h3>
          <div className="flex items-center gap-2">
            <label className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">{t('macro.date')}</label>
            <button
              type="button"
              onClick={() => dateInputRef.current?.showPicker?.()}
              className="p-1.5 rounded-lg text-gray-500 hover:text-white hover:bg-gray-800 transition-colors"
              aria-label={t('macro.openDatePicker')}
            >
              <Calendar size={14} />
            </button>
            <input
              ref={dateInputRef}
              type="date"
              value={dateStr}
              onChange={(e) => setDateStr(e.target.value)}
              className="bg-black border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 outline-none focus:border-[#CCFF00] transition-colors"
            />
          </div>
        </div>

        {/* Content Container */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 md:p-8">

          {/* Content */}
          {subTab === 'summary' ? (
          <>
            {dailySummaryLoading && (
              <p className="text-sm text-gray-500">{t('macro.loadingDaily')}</p>
            )}
            {!dailySummaryLoading && dailySummary && (
              <div className="space-y-8 cursor-default select-text max-w-5xl" role="article">
                <div className="flex items-center gap-2 mb-3">
                  <span className="inline-block px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest" style={{ backgroundColor: 'rgba(204, 255, 0, 0.15)', color: '#CCFF00' }}>
                    {t('macro.dailySummary')}
                  </span>
                  <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">{dateStr}</span>
                </div>
                <h2 className="text-2xl font-black leading-tight text-white mb-3">{dailySummary.title ?? '—'}</h2>
                <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap bg-[#0c0c0c] p-5 rounded-xl border border-gray-900">
                  {dailySummary.summary ?? '—'}
                </p>
                {dailySummary.summary_bullets && Array.isArray(dailySummary.summary_bullets) && dailySummary.summary_bullets.length > 0 && (
                  <section>
                    <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('macro.keyPoints')}</h3>
                    <div className="bg-[#0c0c0c] p-5 rounded-xl border border-gray-900">
                      <ul className="list-disc list-inside text-sm text-gray-300 space-y-2">
                        {dailySummary.summary_bullets.map((bullet, bi) => (
                          <li key={bi} className="leading-relaxed">{typeof bullet === 'string' ? bullet : String(bullet)}</li>
                        ))}
                      </ul>
                    </div>
                  </section>
                )}
              </div>
            )}
            {!dailySummaryLoading && !dailySummary && (
              <p className="text-sm text-gray-500">{t('macro.noDailySummary')}</p>
            )}
            </>
          ) : (
            /* Topic sub-tab: desktop = list left + article right; mobile = title page first, then full-screen article with back */
            <div className="flex flex-col md:flex-row min-h-[480px] -m-4 sm:-m-6 md:-m-8 -mb-4 sm:-mb-6 md:-mb-8 w-full">
            {/* Left: past week list – desktop always; on mobile hidden when article open so article is full-screen */}
            <div className={`w-full md:w-[min(380px,28%)] md:min-w-[280px] flex-shrink-0 overflow-y-auto border-r-0 md:border-r border-gray-800 p-4 sm:p-6 md:p-6 ${hasMacroDetail ? 'hidden md:block' : ''}`}>
              <h4 className="text-[10px] font-bold uppercase text-gray-500 tracking-wider mb-3">
                Past week
              </h4>
              {pastWeekLoading && (
                <p className="text-sm text-gray-500">Loading past week…</p>
              )}
              {!pastWeekLoading && pastWeekWithCoverage.length > 0 && (
                <div className="space-y-3">
                  {pastWeekWithCoverage.map((item, i) => {
                    const d = typeof item.as_of_date === 'string' ? item.as_of_date : String(item.as_of_date);
                    const isSelected = selectedBriefDate === d;
                    return (
                      <button
                        key={`${d}-${i}`}
                        type="button"
                        onClick={() => setSelectedBriefDate(d)}
                        className={`group block w-full text-left p-4 rounded-xl border transition-all ${isSelected ? 'bg-[#0c0c0c] border-[#CCFF00] border-l-2 border-l-[#CCFF00]' : 'bg-[#0a0a0a]/50 border border-gray-800 border-l-2 border-l-[#CCFF00]/40 hover:border-gray-600'}`}
                      >
                        <div className="text-[9px] font-bold uppercase text-gray-500 tracking-wider mb-1.5">
                          {d}
                        </div>
                        <h4 className={`text-sm font-bold mb-1 leading-snug transition-colors ${isSelected ? 'text-[#CCFF00]' : 'text-gray-100 group-hover:text-[#CCFF00]'}`}>{item.title ?? '—'}</h4>
                        <p className="text-xs text-gray-400 line-clamp-2 leading-relaxed">{item.summary ?? '—'}</p>
                      </button>
                    );
                  })}
                </div>
              )}
              {!pastWeekLoading && pastWeekWithCoverage.length === 0 && (
                <p className="text-sm text-gray-500">{t('macro.noBriefsWithCoverage')}</p>
              )}
            </div>

            {/* Right: full article – on mobile full-screen when open (list hidden); desktop list left + article right */}
            <div className={`flex-1 min-w-0 flex flex-col bg-[#080808] md:border-l border-gray-800 overflow-hidden ${hasMacroDetail ? 'min-h-[100dvh] md:min-h-0' : ''}`}>
              {/* Mobile only: back to list so user can return to title page */}
              {hasMacroDetail && (
                <div className="flex md:hidden p-4 border-b border-gray-900 flex-shrink-0">
                  <button type="button" onClick={handleCloseMacroDetail} className="flex items-center gap-2 text-gray-400 hover:text-white transition-colors">
                    <ArrowLeft size={20} />
                    <span className="text-sm font-bold uppercase tracking-wider">{t('stockDetail.backToList')}</span>
                  </button>
                </div>
              )}
              {!selectedBriefDate && (
                <div className="flex-1 flex items-center justify-center p-8">
                  <p className="text-sm text-gray-500">Click a title to open the article.</p>
                </div>
              )}
              {selectedBriefDate && topicLoading && (
                <div className="flex-1 flex items-center justify-center p-8">
                  <p className="text-sm text-gray-500">Loading brief…</p>
                </div>
              )}
              {selectedBriefDate && !topicLoading && topicError && (
                <div className="p-4 border-b border-gray-900 flex items-center justify-between flex-shrink-0">
                  <span className="text-sm text-amber-500">{topicError}</span>
                  <button onClick={() => { setSelectedBriefDate(null); setTopicBrief(null); setTopicError(null); }} className="p-1.5 hover:bg-gray-800 rounded-full transition-colors text-gray-500 hover:text-white"><X size={18} /></button>
                </div>
              )}
              {selectedBriefDate && !topicLoading && !topicError && topicBrief && (
                <>
                  {!topicBrief.coverage_gap && (
                    <div className="p-4 border-b border-gray-900 flex items-center justify-between flex-shrink-0">
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest" style={{ backgroundColor: 'rgba(204, 255, 0, 0.15)', color: '#CCFF00' }}>
                          {topicBrief.topic ?? topicLabel(subTab)}
                        </span>
                        <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">{selectedBriefDate}</span>
                      </div>
                      <button onClick={() => { setSelectedBriefDate(null); setTopicBrief(null); setTopicError(null); }} className="p-1.5 hover:bg-gray-800 rounded-full transition-colors text-gray-500 hover:text-white"><X size={18} /></button>
                    </div>
                  )}
                  <div className="flex-1 overflow-y-auto p-4 sm:p-6 md:p-8 space-y-10 scrollbar-hide">
                    {topicBrief.coverage_gap ? (
                      <p className="text-sm text-gray-500">{t('macro.limitedCoverage')}</p>
                    ) : (
                    <>
                    <h2 className="text-2xl font-black leading-tight text-white mb-1">{topicBrief.title ?? '—'}</h2>
                    {topicBrief.summary && (
                      <p className="text-sm text-gray-200 leading-relaxed whitespace-pre-wrap pl-4 border-l-2 border-l-[#CCFF00]/40 mb-6">{topicBrief.summary}</p>
                    )}
                    {topicBrief.article_bullets && Array.isArray(topicBrief.article_bullets) && topicBrief.article_bullets.length > 0 ? (
                      <div className="space-y-10">
                        {(() => {
                          const bullets = topicBrief.article_bullets as string[];
                          const { blocks } = parseArticleBullets(bullets);
                          return blocks.map((block, bi) => {
                            if (block.type === 'paragraph') {
                              if (bi === 0 && topicBrief.summary) return null;
                              return (
                                <section key={bi}>
                                  <p className="text-sm text-gray-300 leading-relaxed bg-[#0c0c0c] p-5 rounded-xl border border-gray-900">{block.text}</p>
                                </section>
                              );
                            }
                            if (block.type === 'table') {
                              return (
                                <section key={bi}>
                                  <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{block.header}</h3>
                                  {/* Mobile: card per row to avoid truncation */}
                                  <div className="md:hidden space-y-3">
                                    {block.dataRows.map((row, ri) => (
                                      <div key={ri} className="rounded-xl border border-gray-900 p-4 space-y-2 bg-[#0c0c0c]">
                                        {block.columns.map((_, ci) => (
                                          <div key={ci}>
                                            <div className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-0.5">{block.columns[ci]}</div>
                                            <div className="text-sm text-gray-300 leading-relaxed">{ci === 0 ? <span className="font-medium text-[#CCFF00]/90">{row[ci] ?? ''}</span> : (row[ci] ?? '')}</div>
                                          </div>
                                        ))}
                                      </div>
                                    ))}
                                  </div>
                                  {/* Desktop: table */}
                                  <div className="hidden md:block overflow-x-auto rounded-xl border border-gray-900 bg-[#0c0c0c]">
                                    <table className="w-full text-sm text-gray-300 border-collapse min-w-[400px]">
                                      <thead>
                                        <tr className="border-b border-gray-800">
                                          {block.columns.map((col, ci) => (
                                            <th key={ci} className="text-left py-2.5 px-4 font-semibold text-gray-400">{col}</th>
                                          ))}
                                        </tr>
                                      </thead>
                                      <tbody>
                                        {block.dataRows.map((row, ri) => (
                                          <tr key={ri} className="border-b border-gray-800/50 last:border-0">
                                            {block.columns.map((_, ci) => (
                                              <td key={ci} className="py-2.5 px-4 align-top leading-relaxed">{ci === 0 ? <span className="font-medium text-[#CCFF00]/90">{row[ci] ?? ''}</span> : (row[ci] ?? '')}</td>
                                            ))}
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  </div>
                                </section>
                              );
                            }
                            if (block.type === 'bullet_links') {
                              return (
                                <section key={bi}>
                                  <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{block.header}</h3>
                                  <div className="bg-[#0c0c0c] p-5 rounded-xl border border-gray-900">
                                    <ul className="list-disc list-inside text-sm text-gray-300 space-y-2">
                                      {block.items.map((item, ri) => (
                                        <li key={ri} className="leading-relaxed">
                                          {item.url ? (
                                            <a href={item.url} target="_blank" rel="noopener noreferrer" className="text-[#CCFF00] hover:underline transition-colors">
                                              {cleanLinkText(item.text)}
                                            </a>
                                          ) : (
                                            <span>{cleanLinkText(item.text)}</span>
                                          )}
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                </section>
                              );
                            }
                            if (block.type === 'links') {
                              return (
                                <section key={bi}>
                                  <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{block.header}</h3>
                                  <div className="bg-[#0c0c0c] p-5 rounded-xl border border-gray-900">
                                    <ul className="list-none space-y-2">
                                      {block.links.map((link, ri) => (
                                        <li key={ri}>
                                          {link.url ? (
                                            <a href={link.url} target="_blank" rel="noopener noreferrer" className="text-sm text-[#CCFF00] hover:underline leading-relaxed transition-colors">
                                              {cleanLinkText(link.title || link.url)}
                                            </a>
                                          ) : (
                                            <span className="text-sm text-gray-500">{cleanLinkText(link.title)}</span>
                                          )}
                                        </li>
                                      ))}
                                    </ul>
                                  </div>
                                </section>
                              );
                            }
                            if (block.type === 'kv') {
                              return (
                                <section key={bi}>
                                  <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{block.header}</h3>
                                  {/* Mobile: stacked key/value cards */}
                                  <div className="md:hidden space-y-3">
                                    {block.rows.map((row, ri) => (
                                      <div key={ri} className="rounded-xl border border-gray-900 p-4 bg-[#0c0c0c]">
                                        <div className="text-[10px] font-semibold text-[#CCFF00]/90 uppercase tracking-wider mb-1.5">{row.key}</div>
                                        <div className="text-sm text-gray-300 leading-relaxed">{row.value}</div>
                                      </div>
                                    ))}
                                  </div>
                                  {/* Desktop: table or list */}
                                  <div className="hidden md:block rounded-xl border border-gray-900 bg-[#0c0c0c] overflow-hidden">
                                    {block.shortEnough ? (
                                      <table className="w-full text-sm text-gray-300 border-collapse">
                                        <thead>
                                          <tr className="border-b border-gray-800">
                                            <th className="text-left py-2.5 px-4 font-semibold text-gray-400 w-[100px]">Key</th>
                                            <th className="text-left py-2.5 px-4 font-semibold text-gray-400">Details</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {block.rows.map((row, ri) => (
                                            <tr key={ri} className="border-b border-gray-800/50 last:border-0">
                                              <td className="py-2.5 px-4 align-top font-medium text-[#CCFF00]/90 whitespace-nowrap">{row.key}</td>
                                              <td className="py-2.5 px-4 leading-relaxed">{row.value}</td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    ) : (
                                      <div className="p-5">
                                        <ul className="list-disc list-inside text-sm text-gray-300 space-y-1.5">
                                          {block.rows.map((row, ri) => (
                                            <li key={ri} className="leading-relaxed"><span className="font-medium text-[#CCFF00]/90">{row.key}:</span> {row.value}</li>
                                          ))}
                                        </ul>
                                      </div>
                                    )}
                                  </div>
                                </section>
                              );
                            }
                            if (bi === 0 && topicBrief.summary) return null;
                            return (
                              <section key={bi}>
                                <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{block.subTitle}</h3>
                                <p className="text-sm text-gray-300 leading-relaxed bg-[#0c0c0c] p-5 rounded-xl border border-gray-900">{block.content}</p>
                              </section>
                            );
                          });
                        })()}
                      </div>
                    ) : (
                      <div className="space-y-10">
                        {(() => {
                          let bullets: string[] = [];
                          const raw = topicBrief.summary_bullets;
                          if (Array.isArray(raw)) {
                            bullets = raw.map(b => (b != null ? String(b) : '')).filter(Boolean);
                          } else if (typeof raw === 'string') {
                            try {
                              const parsed = JSON.parse(raw);
                              bullets = Array.isArray(parsed) ? parsed.map(b => (b != null ? String(b) : '')).filter(Boolean) : [];
                            } catch {
                              bullets = [];
                            }
                          }
                          return bullets.length > 0 ? (
                            <section>
                              <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('macro.keyPoints')}</h3>
                              <div className="bg-[#0c0c0c] p-5 rounded-xl border border-gray-900">
                                <ul className="list-disc list-inside text-sm text-gray-300 space-y-2">
                                  {bullets.map((bullet, i) => (
                                    <li key={i} className="leading-relaxed">{bullet.replace(/^\s*[•\-]\s*/, '').trim()}</li>
                                  ))}
                                </ul>
                              </div>
                            </section>
                          ) : null;
                        })()}
                      </div>
                    )}
                  </>
                    )}
                  </div>
                </>
              )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default MacroView;
