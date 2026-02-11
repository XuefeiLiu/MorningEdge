import React, { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import { Stock, NewsItem, NewsCategory, SentimentType } from '../types';
import { Calendar, Check, Sparkles, X, MessageSquare, Save, ChevronRight, ArrowLeft } from 'lucide-react';
import { DarkDatePicker } from './DarkDatePicker';
import { useLocale } from '../i18n/context';
import { getDirectionColor } from '../constants';
import TradingViewChart from './TradingViewChart';
import NewsFilterPanel from './NewsFilterPanel';
import LongStoryTimeline from './LongStoryTimeline';
import { API_BASE } from '../api';

interface StockDetailProps {
  stock: Stock;
}

type RightTab = 'Storyline' | 'Price Impact';

/** Supporting article from API: NewsItem fields plus url and relation_type */
type SupportingArticle = NewsItem & { url?: string; relation_type?: string };

interface NarrativeCluster {
  id: string;
  title: string;
  summary: string;
  timestamp: string;
  sentiment: SentimentType;
  newsCount: number;
  sourceEvents: SupportingArticle[];
  /** Set when from API; used to fetch supporting articles on click */
  storylineId?: number;
  /** short | long | filing | overnight; from API story_type (long from long_stories; overnight from story table) */
  storyType?: 'short' | 'long' | 'filing' | 'overnight';
  /** When storyType='filing', the storyline (short or long) that this insight was generated from */
  sourceStorylineId?: string | number | null;
  /** Overnight pipeline: session (OVERNIGHT/INTRADAY/MIXED) and risk/impact for card display */
  session_label?: string;
  /** UI label: OVERNIGHT (published > 4pm ET) or Intraday (published <= 4pm ET) */
  session_display_label?: 'OVERNIGHT' | 'Intraday' | 'Mixed';
  session_confidence?: number;
  prob_move_ge_1pct?: number;
  prob_move_ge_2pct?: number;
  risk_confidence?: number;
  direction_bias?: string;
  expected_abs_move_pct?: number;
  is_filing_related?: boolean;
  risk_drivers?: string[];
}

// Simple deterministic "random" based on a seed string
const seededRandom = (seed: string) => {
  let h = 0;
  for (let i = 0; i < seed.length; i++) {
    h = Math.imul(31, h) + seed.charCodeAt(i) | 0;
  }
  return () => {
    h = Math.imul(h ^ h >>> 16, 2246822507) | 0;
    h = Math.imul(h ^ h >>> 13, 3266489909) | 0;
    return (h >>> 0) / 4294967296;
  };
};

// Temporarily disabled Industry and Sentiment categories (code preserved for future use)
// Macro has its own top-level tab; Narrative view is Stock-only.
const CATEGORIES: NewsCategory[] = ['Stock'];
const TIMEFRAMES = ['1D', '2D', '3D', '1W'];

const CATEGORY_COLORS: Record<NewsCategory, string> = {
  Stock: '#3B82F6',     // Vibrant Blue
  Industry: '#00D2FF',  // Cyan
  Macro: '#FF8A00',     // Orange
  Sentiment: '#B266FF'  // Purple
};

const SOURCES = ['Bloomberg', 'WSJ', 'Reuters', 'CNBC', 'Financial Times', 'MarketWatch', 'Yahoo Finance', 'The Verge', 'Barron\'s', 'Forbes'];

/** Format ISO timestamp for UI display in local timezone. */
function formatTimestampLocal(isoString: string): string {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  const formatter = new Intl.DateTimeFormat('en-CA', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
  return formatter.format(date).replace(', ', ' ');
}

const generateMockNews = (symbol: string, stockName: string): NewsItem[] => {
  const news: NewsItem[] = [];
  const rand = seededRandom(symbol);
  const startDate = new Date('2024-07-01T00:00:00Z');
  const today = new Date();
  
  const templates: Record<NewsCategory, Array<{ title: string; summary: string; sentiment: SentimentType }>> = {
    Stock: [
      { title: `${symbol} beats quarterly estimates as margins expand`, summary: `${stockName} reported earnings that surprised analysts, driven by operational efficiencies.`, sentiment: 'Bullish' },
      { title: `Internal memo reveals ${symbol} pivoting strategy towards AI`, summary: `Leadership at ${symbol} is reallocating resources to accelerate long-term growth initiatives.`, sentiment: 'Bullish' },
      { title: `${symbol} faces legal hurdle in core business segment`, summary: `Regulatory bodies are reviewing certain practices at ${stockName} that might impact near-term guidance.`, sentiment: 'Bearish' },
      { title: `${symbol} CEO discusses future roadmap in latest interview`, summary: `The executive provided insights into how ${stockName} plans to maintain its competitive moat.`, sentiment: 'Neutral' },
    ],
    Industry: [
      { title: `New competition emerges in ${symbol}'s primary market`, summary: `A well-funded startup is challenging ${stockName}'s market share in key demographics.`, sentiment: 'Bearish' },
      { title: `Industry-wide supply chain bottleneck easing`, summary: `Logistics data suggests that components for companies like ${symbol} are moving faster.`, sentiment: 'Bullish' },
      { title: `Major tech breakthrough could redefine ${symbol}'s sector`, summary: `Researchers have unveiled a new platform that could significantly lower barriers to entry.`, sentiment: 'Neutral' },
      { title: `Global demand for tech services reaches record highs`, summary: `Consumer and enterprise spending trends favor the ecosystem inhabited by ${symbol}.`, sentiment: 'Bullish' },
    ],
    Macro: [
      { title: `Inflation data prints lower than expected, tech rallies`, summary: `CPI reports provide relief for growth stocks like ${symbol} as rate expectations shift.`, sentiment: 'Bullish' },
      { title: `Geopolitical tensions weigh on multinational tech giants`, summary: `Trade frictions between major economies create uncertainty for ${stockName}'s global supply chain.`, sentiment: 'Bearish' },
      { title: `Central bank maintains interest rates at latest meeting`, summary: `The steady rate environment allows companies like ${symbol} to forecast capital expenses with more certainty.`, sentiment: 'Neutral' },
      { title: `Labor market remains tight across high-tech industries`, summary: `Sustained wage growth continues to be a factor for large-scale employers like ${stockName}.`, sentiment: 'Neutral' },
    ],
    Sentiment: [
      { title: `Retail investors show renewed interest in ${symbol}`, summary: `Social media sentiment scores for ${symbol} have hit multi-month highs this week.`, sentiment: 'Bullish' },
      { title: `Institutional funds trimming exposure to ${symbol}`, summary: `Latest 13F filings show some major hedge funds reducing their position in ${stockName}.`, sentiment: 'Bearish' },
      { title: `Options market suggests high volatility for ${symbol}`, summary: `Implied volatility spikes as traders hedge their bets ahead of the upcoming catalyst.`, sentiment: 'Neutral' },
      { title: `Analyst consensus shifts to 'Overweight' for ${symbol}`, summary: `Several major banks have upgraded their outlook on ${stockName} citing undervalued assets.`, sentiment: 'Bullish' },
    ]
  };

  const intervalRanges = [
    { min: 0, max: 1 },
    { min: 1, max: 7 },
    { min: 7, max: 30 },
    { min: 30, max: 90 },
    { min: 90, max: 180 },
    { min: 180, max: (today.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24) }
  ];

  CATEGORIES.forEach(cat => {
    intervalRanges.forEach((range, rangeIdx) => {
      for (let i = 0; i < 2; i++) {
        const templateIdx = Math.floor(rand() * templates[cat].length);
        const template = templates[cat][templateIdx];
        const sourceIdx = Math.floor(rand() * SOURCES.length);
        const source = SOURCES[sourceIdx];
        const daysOffset = range.min + (rand() * (range.max - range.min));
        const timestamp = new Date(today.getTime() - (daysOffset * 24 * 60 * 60 * 1000)).toISOString();
        news.push({ id: `${symbol}-${cat}-${rangeIdx}-${i}`, symbol, timestamp, category: cat, source, title: template.title, summary: template.summary, sentiment: template.sentiment });
      }
    });
  });
  return news;
};

const GLOBAL_NEWS_BASE = [
  { id: 'g1', symbol: 'ALL', timestamp: new Date(Date.now() - 12 * 60 * 60 * 1000).toISOString(), category: 'Macro' as NewsCategory, source: 'Bloomberg', title: 'Global Markets: CPI cooling faster than expected', summary: 'Latest figures suggest a pivot in monetary policy is becoming increasingly likely.', sentiment: 'Bullish' as SentimentType },
  { id: 'g2', symbol: 'ALL', timestamp: new Date('2024-08-15T14:00:00Z').toISOString(), category: 'Industry' as NewsCategory, source: 'CNBC', title: 'Semiconductor shortage fears resurface', summary: 'Logistics delays are causing ripples in the global chip supply chain.', sentiment: 'Bearish' as SentimentType },
];

const PriceChart: React.FC<{ 
  stock: Stock, 
  news: NewsItem[], 
  timeframe: string, 
  customRange: {start: string, end: string} 
}> = ({ stock, news, timeframe, customRange }) => {
  const { t } = useLocale();
  const [hoveredNews, setHoveredNews] = useState<NewsItem | null>(null);

  const priceHistory = useMemo(() => {
    const points = 100;
    const rand = seededRandom(stock.symbol + timeframe);
    let current = stock.price * 0.9;
    const history = [];
    for (let i = 0; i < points; i++) {
      const vol = 0.02;
      current = current * (1 + (rand() - 0.48) * vol);
      history.push({ x: i, y: current });
    }
    const minY = Math.min(...history.map(p => p.y));
    const maxY = Math.max(...history.map(p => p.y));
    const rangeY = maxY - minY;
    
    return history.map(p => ({
      x: (p.x / (points - 1)) * 100,
      y: 100 - ((p.y - minY) / rangeY) * 80 - 10
    }));
  }, [stock.symbol, stock.price, timeframe]);

  const newsPoints = useMemo(() => {
    const now = new Date();
    let durationDays = 30;
    let startTimestamp = now.getTime();

    switch (timeframe) {
      case '1D': durationDays = 1; break;
      case '2D': durationDays = 2; break;
      case '3D': durationDays = 3; break;
      case '1W': durationDays = 7; break;
      default:
        durationDays = 1;
    }
    startTimestamp = now.getTime();

    return news.map(item => {
      const itemDate = new Date(item.timestamp);
      const diffMs = startTimestamp - itemDate.getTime();
      const diffDays = diffMs / (1000 * 60 * 60 * 24);
      
      if (diffDays < 0 || diffDays > durationDays) return null;
      
      const xPercent = 100 - (diffDays / durationDays) * 100;
      const closestPoint = priceHistory.reduce((prev, curr) => 
        Math.abs(curr.x - xPercent) < Math.abs(prev.x - xPercent) ? curr : prev
      );

      return { ...item, x: xPercent, y: closestPoint.y };
    }).filter(Boolean) as (NewsItem & { x: number, y: number })[];
  }, [news, timeframe, customRange, priceHistory]);

  const pathData = `M ${priceHistory[0].x} ${priceHistory[0].y} ` + 
    priceHistory.slice(1).map(p => `L ${p.x} ${p.y}`).join(' ');

  const getSentimentColor = (sentiment: string) => {
    switch (sentiment) {
      case 'Bullish': return '#CCFF00';
      case 'Bearish': return '#ff5000';
      default: return '#666666';
    }
  };

  return (
    <div className="w-full">
      <div className="flex items-end justify-between mb-10">
        <div>
          <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1">{t('stockDetail.marketCorrelation')}</div>
          <div className="flex items-baseline gap-4">
            <h2 className="text-4xl font-bold tracking-tighter">${stock.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}</h2>
            <span className={`text-sm font-bold ${stock.change >= 0 ? 'text-[#CCFF00]' : 'text-[#ff5000]'}`}>
              {stock.change >= 0 ? '+' : ''}{stock.change.toFixed(2)} ({stock.changePercent.toFixed(2)}%)
            </span>
          </div>
        </div>
        <div className="text-right hidden sm:block">
          <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1">{t('stockDetail.analyzedPeriod')}</div>
          <div className="text-sm font-bold text-gray-300">{timeframe} {t('stockDetail.view')}</div>
        </div>
      </div>

      <div className="relative w-full aspect-[21/9] bg-[#080808] rounded-xl border border-gray-900 overflow-hidden group/chart">
        <div className="absolute inset-0 opacity-10 pointer-events-none">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="absolute w-full h-[1px] bg-white" style={{ top: `${(i + 1) * 20}%` }} />
          ))}
          {Array.from({ length: 10 }).map((_, i) => (
            <div key={i} className="absolute h-full w-[1px] bg-white" style={{ left: `${(i + 1) * 10}%` }} />
          ))}
        </div>

        <svg viewBox="0 0 100 100" className="absolute inset-0 w-full h-full overflow-visible" preserveAspectRatio="none">
          <path 
            d={pathData} 
            fill="none" 
            stroke={stock.change >= 0 ? "#CCFF00" : "#ff5000"} 
            strokeWidth="1.5"
            strokeLinejoin="round"
            className="drop-shadow-[0_0_8px_rgba(204,255,0,0.3)]"
          />
          
          {newsPoints.map((point) => (
            <circle
              key={point.id}
              cx={point.x}
              cy={point.y}
              r="1.2"
              fill={CATEGORY_COLORS[point.category]}
              stroke="#000"
              strokeWidth="0.5"
              className="cursor-pointer transition-all hover:scale-150 relative z-20"
              onMouseEnter={() => setHoveredNews(point)}
              onMouseLeave={() => setHoveredNews(null)}
            />
          ))}
        </svg>

        {hoveredNews && (
          <div 
            className="absolute z-50 bg-[#121212] border border-gray-800 p-3 rounded-lg shadow-2xl pointer-events-none animate-in fade-in zoom-in-95 duration-200 w-64"
            style={{ 
              left: `${(hoveredNews as any).x}%`, 
              top: `${(hoveredNews as any).y}%`,
              transform: 'translate(-50%, -120%)'
            }}
          >
            <div className="flex items-center gap-2 mb-1.5">
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_COLORS[hoveredNews.category] }} />
              <span className="text-[9px] font-black uppercase text-gray-500 tracking-wider">
                {hoveredNews.category} • {hoveredNews.source}
              </span>
            </div>
            <h5 className="text-[11px] font-bold text-white mb-1 leading-snug line-clamp-2">{hoveredNews.title}</h5>
            <div className="flex items-center justify-between mt-2">
              <span className="text-[9px] font-bold uppercase tracking-widest" style={{ color: getSentimentColor(hoveredNews.sentiment) }}>{hoveredNews.sentiment}</span>
              <span className="text-[9px] font-bold text-gray-600">{formatTimestampLocal(hoveredNews.timestamp)}</span>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-6 mt-8 p-4 bg-[#0a0a0a] rounded-lg border border-gray-900">
        <div className="text-[10px] font-bold text-gray-600 uppercase tracking-widest mr-2 flex items-center">Event Legend</div>
        {CATEGORIES.map(cat => (
          <div key={cat} className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: CATEGORY_COLORS[cat] }} />
            <span className="text-[10px] font-bold text-gray-400 uppercase tracking-tighter">{cat}</span>
          </div>
        ))}
      </div>
      
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-8">
        {[
          { label: 'Volatility', value: 'High', color: '#ff5000' },
          { label: 'Narrative Power', value: '88/100', color: '#CCFF00' },
          { label: 'Market Sentiment', value: 'Bullish', color: '#CCFF00' },
          { label: 'Industry Rank', value: '#12', color: 'white' },
        ].map((metric, i) => (
          <div key={i} className="bg-[#0a0a0a] border border-gray-900 p-4 rounded-xl">
            <div className="text-[9px] font-bold text-gray-600 uppercase tracking-widest mb-1">{metric.label}</div>
            <div className="text-sm font-bold" style={{ color: metric.color }}>{metric.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

interface StorylineFromAPI {
  id: number;
  ticker: string;
  canonical_theme: string;
  summary: string;
  title?: string;
  story_type?: 'short' | 'long' | 'filing';
  source_storyline_id?: string | null;
  created_at: string | null;
  last_updated_at: string | null;
}

/** Long story from backend via GET /long-stories. */
interface LongStoryFromAPI {
  id: string;
  ticker: string;
  title?: string | null;
  canonical_theme?: string | null;
  summary?: string | null;
  impact_level?: string | null;
  article_count?: number | null;
  created_at?: string | null;
  last_updated_at?: string | null;
  /** Latest article published date; used for timeline display (day of most recent article). */
  latest_article_published_at?: string | null;
}

/** Overnight story from backend story table via GET /overnight-stories. */
interface OvernightStoryFromAPI {
  id: string;
  ticker?: string | null;
  asof_date: string;
  title: string;
  summary: string;
  topics: string[];
  session_label: string;
  session_confidence?: number | null;
  prob_move_ge_1pct?: number | null;
  prob_move_ge_2pct?: number | null;
  expected_abs_move_pct?: number | null;
  direction_bias?: string | null;
  risk_confidence?: number | null;
  risk_drivers: string[];
  is_filing_related: boolean;
  created_at?: string | null;
  latest_article_published_at?: string | null;
}

/** One month in long-story timeline (GET /long-stories/{id}/timeline or GET /storylines/{id}/timeline) */
interface TimelineMonth {
  month: string;
  articles: Array<{ id: number; ticker: string; title: string; summary?: string; url?: string; source?: string; published_at?: string; relation_type?: string }>;
}

const StockDetail: React.FC<StockDetailProps> = ({ stock }) => {
  const { t, locale } = useLocale();
  const [selectedCategories, setSelectedCategories] = useState<NewsCategory[]>(['Stock']);
  const [selectedTimeframe, setSelectedTimeframe] = useState('1D');
  const [customRange, setCustomRange] = useState({ start: '', end: '' });
  const storylineDetailPanelRef = useRef<HTMLDivElement>(null);
  const [activeTab, setActiveTab] = useState<RightTab>('Storyline');
  const [isCausalMode, setIsCausalMode] = useState(false);
  
  // Storylines from DB (for category Stock)
  const [stockStorylines, setStockStorylines] = useState<StorylineFromAPI[]>([]);
  const [longStories, setLongStories] = useState<LongStoryFromAPI[]>([]);
  const [loadingStorylines, setLoadingStorylines] = useState(false);
  const [storylinesFetchError, setStorylinesFetchError] = useState(false);
  const [longStoriesFetchError, setLongStoriesFetchError] = useState(false);

  // Stock news from API
  const [stockNews, setStockNews] = useState<NewsItem[]>([]);
  const [loadingStockNews, setLoadingStockNews] = useState(false);
  
  // Macro news from API
  const [macroNews, setMacroNews] = useState<NewsItem[]>([]);
  const [loadingMacroNews, setLoadingMacroNews] = useState(false);
  
  // States for Detail Overlay
  const [activeDetailNews, setActiveDetailNews] = useState<NewsItem | null>(null);
  const [activeDetailNarrative, setActiveDetailNarrative] = useState<NarrativeCluster | null>(null);
  const [expandedSupportingId, setExpandedSupportingId] = useState<string | null>(null);
  const [supportingArticlesStatus, setSupportingArticlesStatus] = useState<'idle' | 'loading' | 'loaded' | 'error'>('idle');
  const [filingCitations, setFilingCitations] = useState<Array<{ chunk_id: string; text: string; filing_url: string; form_type?: string; filed_date?: string; filing_title?: string; summary?: string; is_table?: boolean }>>([]);
  const [filingCitationsStatus, setFilingCitationsStatus] = useState<'idle' | 'loading' | 'loaded' | 'error'>('idle');
  const [expandedFilingCitationId, setExpandedFilingCitationId] = useState<string | null>(null);
  const [formattedChunkByCitationId, setFormattedChunkByCitationId] = useState<Record<string, string>>({});
  const [formattedChunkLoadingById, setFormattedChunkLoadingById] = useState<Record<string, boolean>>({});
  const [formattedChunkErrorById, setFormattedChunkErrorById] = useState<Record<string, boolean>>({});
  const [userComments, setUserComments] = useState<Record<string, string>>({});
  const [currentComment, setCurrentComment] = useState("");

  // Long-story timeline view (now uses split view like Current News/SEC Insights)
  const [longStoryTimelineOpen, setLongStoryTimelineOpen] = useState(false);
  const [activeLongStoryId, setActiveLongStoryId] = useState<string | null>(null);
  const [longStoryTimeline, setLongStoryTimeline] = useState<TimelineMonth[] | null>(null);
  const [longStoryTimelineLoading, setLongStoryTimelineLoading] = useState(false);
  const [longStoryTimelineTitle, setLongStoryTimelineTitle] = useState<string>('');
  const [longStoryTimelineSummary, setLongStoryTimelineSummary] = useState<string>('');
  const [longStoryTimelineTheme, setLongStoryTimelineTheme] = useState<string>('');
  const [longStoryTotalArticles, setLongStoryTotalArticles] = useState<number>(0);
  const [expandedLongStoryArticleId, setExpandedLongStoryArticleId] = useState<number | null>(null);

  // Storyline subtabs when Stock: Overnight Impact (story table) | Long Story
  const [storylineSubtab, setStorylineSubtab] = useState<'overnightImpact' | 'longStory'>('overnightImpact');
  const [overnightStories, setOvernightStories] = useState<OvernightStoryFromAPI[]>([]);

  const toggleCategory = (cat: NewsCategory) => {
    setSelectedCategories(prev => prev.includes(cat) ? prev.filter(c => c !== cat) : [...prev, cat]);
  };

  // When user expands a filing citation, fetch LLM-formatted chunk (cache by chunk_id)
  useEffect(() => {
    const chunkId = expandedFilingCitationId;
    if (!chunkId || filingCitationsStatus !== 'loaded') return;
    const cit = filingCitations.find((c) => c.chunk_id === chunkId);
    if (!cit?.text?.trim()) return;
    if (formattedChunkByCitationId[chunkId]) return; // already have formatted
    setFormattedChunkLoadingById((prev) => ({ ...prev, [chunkId]: true }));
    setFormattedChunkErrorById((prev) => ({ ...prev, [chunkId]: false }));
    fetch(`${API_BASE}/storylines/format-filing-chunk`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chunk_text: cit.text }),
    })
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data: { formatted: string }) => {
        setFormattedChunkByCitationId((prev) => ({ ...prev, [chunkId]: data.formatted || cit.text }));
        setFormattedChunkErrorById((prev) => ({ ...prev, [chunkId]: false }));
      })
      .catch(() => {
        setFormattedChunkErrorById((prev) => ({ ...prev, [chunkId]: true }));
      })
      .finally(() => {
        setFormattedChunkLoadingById((prev) => ({ ...prev, [chunkId]: false }));
      });
  }, [expandedFilingCitationId, filingCitationsStatus, filingCitations, formattedChunkByCitationId]);

  // Date range: custom (calendar) or preset — 1D = from now to 24 hours ago, 2D = 48h ago, 3D = 72h ago, 1W = 7 days ago
  // Preset uses current moment as end; custom range uses calendar day boundaries in local timezone
  // Custom range takes priority over selectedTimeframe. API receives UTC ISO strings.
  const getDateRange = useCallback(() => {
    const dayMs = 24 * 60 * 60 * 1000;
    
    // Check if custom range is set (either start or end has a value)
    const hasCustomRange = customRange.start.trim() !== '' || customRange.end.trim() !== '';
    
    if (hasCustomRange) {
      // Custom date range: use custom range (user input is in local timezone)
      // If only start is set, use start as both start and end (single day)
      // If only end is set, use end as both start and end (single day)
      // If both are set, use the range [start, end]
      const startDateStr = customRange.start.trim() || customRange.end.trim();
      const endDateStr = customRange.end.trim() || customRange.start.trim();
      
      if (startDateStr && endDateStr) {
        // Parse user input as local timezone dates (YYYY-MM-DD format)
        const [startYear, startMonth, startDay] = startDateStr.split('-').map(Number);
        const [endYear, endMonth, endDay] = endDateStr.split('-').map(Number);
        
        // Create Date objects representing local timezone boundaries
        // new Date(year, month, day, hour, minute, second) creates a Date object
        // that represents the specified LOCAL time, which JavaScript stores internally as UTC
        // Example: If user is UTC-5 and selects "2026-01-29":
        //   - Local "2026-01-29 00:00:00" = UTC "2026-01-29T05:00:00.000Z"
        //   - Local "2026-01-29 23:59:59" = UTC "2026-01-30T04:59:59.999Z"
        const startDateLocal = new Date(startYear, startMonth - 1, startDay, 0, 0, 0, 0);
        const endDateLocal = new Date(endYear, endMonth - 1, endDay, 23, 59, 59, 999);
        
        // These Date objects are stored internally as UTC but represent local time boundaries
        // When converted to ISO string, they will be in UTC format for API calls
        const startDate = startDateLocal;
        const endDate = endDateLocal;
        
        // Ensure start <= end (swap if needed)
        if (startDate > endDate) {
          return { startDate: endDate, endDate: startDate };
        }
        return { startDate, endDate };
      }
    }
    
    // No custom range: use preset timeframe — from now back by duration (1D = last 24 hours, etc.)
    const now = new Date();
    let durationMs: number;
    switch (selectedTimeframe) {
      case '1D':
        durationMs = 1 * dayMs;
        break;
      case '2D':
        durationMs = 2 * dayMs;
        break;
      case '3D':
        durationMs = 3 * dayMs;
        break;
      case '1W':
        durationMs = 7 * dayMs;
        break;
      default:
        durationMs = 1 * dayMs;
    }
    const endDate = now;
    const startDate = new Date(now.getTime() - durationMs);
    return { startDate, endDate };
  }, [customRange.start, customRange.end, selectedTimeframe]);

  // Fetch storylines: use start_date and end_date for precise date filtering
  useEffect(() => {
    if (!selectedCategories.includes('Stock')) {
      setStockStorylines([]);
      setLongStories([]);
      setStorylinesFetchError(false);
      setLongStoriesFetchError(false);
      return;
    }
    setLoadingStorylines(true);
    setStorylinesFetchError(false);
    const ticker = stock.symbol?.trim().toUpperCase();
    if (!ticker) {
      setLoadingStorylines(false);
      return;
    }
    
    // Get date range for API call (used for both storylines and long stories)
    const { startDate, endDate } = getDateRange();
    const startDateStr = startDate.toISOString();
    const endDateStr = endDate.toISOString();
    
    let storylinesDone = false;
    let longStoriesDone = false;
    let overnightDone = false;
    const maybeDone = (): void => {
      if (storylinesDone && longStoriesDone && overnightDone) setLoadingStorylines(false);
    };

    // Fetch storylines with start_date and end_date parameters (used for insightMap etc.)
    fetch(`${API_BASE}/storylines?ticker=${encodeURIComponent(ticker)}&start_date=${encodeURIComponent(startDateStr)}&end_date=${encodeURIComponent(endDateStr)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data: StorylineFromAPI[]) => {
        const list = Array.isArray(data) ? data : [];
        setStockStorylines(list);
        setStorylinesFetchError(false);
        storylinesDone = true;
        maybeDone();
      })
      .catch(() => {
        setStockStorylines([]);
        setStorylinesFetchError(false);
        storylinesDone = true;
        maybeDone();
      });

    // Fetch overnight stories (Overnight Impact tab)
    fetch(`${API_BASE}/overnight-stories?ticker=${encodeURIComponent(ticker)}&start_date=${encodeURIComponent(startDateStr)}&end_date=${encodeURIComponent(endDateStr)}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data: OvernightStoryFromAPI[]) => {
        setOvernightStories(Array.isArray(data) ? data : []);
        overnightDone = true;
        maybeDone();
      })
      .catch(() => {
        setOvernightStories([]);
        overnightDone = true;
        maybeDone();
      });
    
    // Fetch all long stories for ticker (no date filter — Long Story tab shows all narratives for the stock)
    setLongStoriesFetchError(false);
    fetch(`${API_BASE}/long-stories?ticker=${encodeURIComponent(ticker)}`)
      .then((res) => {
        if (!res.ok) {
          setLongStoriesFetchError(true);
          return [];
        }
        return res.json();
      })
      .then((data: LongStoryFromAPI[]) => {
        setLongStories(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        setLongStoriesFetchError(true);
        setLongStories([]);
      })
      .finally(() => {
        longStoriesDone = true;
        maybeDone();
      });
  }, [stock.symbol, selectedCategories, getDateRange]);

  // Fetch stock news from API when Stock category is selected
  useEffect(() => {
    if (!selectedCategories.includes('Stock')) {
      setStockNews([]);
      return;
    }
    setLoadingStockNews(true);
    const ticker = stock.symbol?.trim().toUpperCase();
    if (!ticker) {
      setLoadingStockNews(false);
      return;
    }
    
    const { startDate, endDate } = getDateRange();
    const startDateStr = startDate.toISOString();
    const endDateStr = endDate.toISOString();
    
    fetch(`${API_BASE}/news/stock?ticker=${encodeURIComponent(ticker)}&start_date=${encodeURIComponent(startDateStr)}&end_date=${encodeURIComponent(endDateStr)}&limit=100`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data: Array<{ id: number; ticker: string; title: string; summary?: string; url?: string; source: string; published_at: string }>) => {
        // Convert API response to NewsItem format
        const newsItems: NewsItem[] = (Array.isArray(data) ? data : []).map((item) => ({
          id: String(item.id),
          symbol: item.ticker || ticker,
          timestamp: item.published_at,
          category: 'Stock' as NewsCategory,
          source: item.source || 'Unknown',
          title: item.title,
          summary: item.summary || '',
          sentiment: 'Neutral' as SentimentType,
          url: item.url,
        }));
        setStockNews(newsItems);
      })
      .catch((err) => {
        console.error('Error fetching stock news:', err);
        setStockNews([]);
      })
      .finally(() => setLoadingStockNews(false));
  }, [selectedCategories, stock.symbol, selectedTimeframe, customRange]);

  // Fetch macro news from API when Macro category is selected
  useEffect(() => {
    if (!selectedCategories.includes('Macro')) {
      setMacroNews([]);
      return;
    }
    setLoadingMacroNews(true);
    const ticker = stock.symbol?.trim().toUpperCase();
    
    const { startDate, endDate } = getDateRange();
    const startDateStr = startDate.toISOString();
    const endDateStr = endDate.toISOString();
    
    const url = ticker 
      ? `${API_BASE}/news/macro?ticker=${encodeURIComponent(ticker)}&start_date=${encodeURIComponent(startDateStr)}&end_date=${encodeURIComponent(endDateStr)}&limit=100`
      : `${API_BASE}/news/macro?start_date=${encodeURIComponent(startDateStr)}&end_date=${encodeURIComponent(endDateStr)}&limit=100`;
    
    fetch(url)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data: Array<{ id: number; title: string; summary?: string; url?: string; source: string; published_at: string; primary_topic?: string; related_tickers?: string[] }>) => {
        // Convert API response to NewsItem format
        const newsItems: NewsItem[] = (Array.isArray(data) ? data : []).map((item) => ({
          id: String(item.id),
          symbol: ticker || 'ALL',
          timestamp: item.published_at,
          category: 'Macro' as NewsCategory,
          source: item.source || 'Unknown',
          title: item.title,
          summary: item.summary || '',
          sentiment: 'Neutral' as SentimentType,
          url: item.url,
          primaryTopic: item.primary_topic,
          relatedTickers: item.related_tickers,
        }));
        setMacroNews(newsItems);
      })
      .catch((err) => {
        console.error('Error fetching macro news:', err);
        setMacroNews([]);
      })
      .finally(() => setLoadingMacroNews(false));
  }, [selectedCategories, stock.symbol, selectedTimeframe, customRange]);

  // Clear article detail when switching away from Storyline so split view is only on Storyline
  useEffect(() => {
    if (activeTab !== 'Storyline') {
      setActiveDetailNews(null);
      setActiveDetailNarrative(null);
    }
  }, [activeTab]);

  // On mobile, scroll article detail into view when user taps a storyline so they see the article
  useEffect(() => {
    if (!activeDetailNews && !activeDetailNarrative) return;
    const el = storylineDetailPanelRef.current;
    if (el) {
      const t = requestAnimationFrame(() => {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      return () => cancelAnimationFrame(t);
    }
  }, [activeDetailNews, activeDetailNarrative]);

  const filteredNews = useMemo(() => {
    // Use real data from API instead of mock data
    const stockNewsItems = selectedCategories.includes('Stock') ? stockNews : [];
    const macroNewsItems = selectedCategories.includes('Macro') ? macroNews : [];
    
    const combinedNews = [...stockNewsItems, ...macroNewsItems];
    
    // Apply date range filter (client-side filtering as backup to API filtering)
    // Logic: Both item time and user input time are converted to UTC, then compared
    const { startDate, endDate } = getDateRange();
    
    const filtered = combinedNews.filter((item) => {
      // Step 1: Parse UTC timestamp from database (ISO string format, e.g., "2026-02-02T12:00:00Z")
      // new Date(isoString) parses the UTC timestamp and creates a Date object
      // The Date object internally stores UTC time, but methods like getFullYear() return local time values
      const itemDate = new Date(item.timestamp);
      
      // Step 2: Compare dates
      // Both itemDate and startDate/endDate are Date objects that internally store UTC timestamps
      // When comparing Date objects, JavaScript compares their internal UTC timestamps (milliseconds since epoch)
      // This ensures correct comparison regardless of timezone
      const inRange = itemDate >= startDate && itemDate <= endDate;
      return inRange;
    });
    return filtered.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }, [selectedCategories, stockNews, macroNews, customRange, selectedTimeframe]);

  // DB storylines for category Stock: filter by date range and sort by time (latest first)
  const dbTimelineItems = useMemo(() => {
    if (!selectedCategories.includes('Stock') || stockStorylines.length === 0) return [];
    const { startDate, endDate } = getDateRange();
    const items = stockStorylines
      .map((s) => ({
        id: String(s.id),
        title: s.title ?? s.canonical_theme ?? 'Story',
        summary: s.summary || '',
        timestamp: s.latest_article_published_at ?? s.last_updated_at ?? s.created_at ?? new Date().toISOString(),
        sentiment: 'Neutral' as SentimentType,
        newsCount: 0,
        sourceEvents: [] as SupportingArticle[],
        storylineId: s.id,
        storyType: s.story_type ?? undefined,
        sourceStorylineId: s.source_storyline_id ?? null,
      })) as NarrativeCluster[];
    // Filter by date range: timestamp must be within [startDate, endDate]
    // Logic: Both item time and user input time are converted to UTC, then compared
    // Note: item.timestamp is the same field used for display in formatTimestamp(narrative.timestamp)
    // formatTimestamp uses local timezone methods (getFullYear, getMonth, etc.) to display in local time
    const filtered = items.filter((item) => {
      // Step 1: Parse UTC timestamp from database (ISO string format, e.g., "2026-02-02T12:00:00Z")
      // new Date(isoString) parses the UTC timestamp and creates a Date object
      // The Date object internally stores UTC time, but methods like getFullYear() return local time values
      const itemDate = new Date(item.timestamp);
      
      // Step 2: Compare dates
      // Both itemDate and startDate/endDate are Date objects that internally store UTC timestamps
      // When comparing Date objects, JavaScript compares their internal UTC timestamps (milliseconds since epoch)
      // This ensures correct comparison regardless of timezone
      const inRange = itemDate >= startDate && itemDate <= endDate;
      return inRange;
    });
    return filtered.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }, [selectedCategories, stockStorylines, customRange, selectedTimeframe]);

  // Map: source storyline id -> filing (insight) narrative. Used to show "Insight" tag on short/long cards.
  const insightMap = useMemo(() => {
    const map: Record<string, NarrativeCluster> = {};
    for (const n of dbTimelineItems) {
      if (n.storyType === 'filing' && n.sourceStorylineId != null) {
        map[String(n.sourceStorylineId)] = n;
      }
    }
    return map;
  }, [dbTimelineItems]);

  // Filtered by story type for subtabs. Overnight Impact = story table, split by latest_article_published_at: > 4pm ET = Overnight, <= 4pm ET = Intraday.
  const shortItems = useMemo(() => dbTimelineItems.filter((n) => n.storyType === 'short'), [dbTimelineItems]);
  const filingItems = useMemo(() => dbTimelineItems.filter((n) => n.storyType === 'filing'), [dbTimelineItems]);
  const overnightItems = useMemo(() => {
    const { startDate, endDate } = getDateRange();
    const inRange = overnightStories.filter((s) => {
      const pub = s.latest_article_published_at;
      if (!pub) return false;
      const d = new Date(pub);
      return d >= startDate && d <= endDate;
    });
    const mapped = inRange.map(
      (s): NarrativeCluster & { session_display_label: 'OVERNIGHT' | 'Intraday' | 'Mixed' } => {
        const timestamp = s.latest_article_published_at ?? (s.asof_date ? `${s.asof_date}T12:00:00Z` : new Date().toISOString());
        const raw = (s.session_label || '').toUpperCase();
        const session_display_label = raw === 'MIXED' ? 'Mixed' : raw === 'INTRADAY' ? 'Intraday' : 'OVERNIGHT';
        return {
          id: s.id,
          title: s.title || 'Story',
          summary: s.summary || '',
          timestamp,
          sentiment: 'Neutral',
          newsCount: 0,
          sourceEvents: [],
          storylineId: undefined,
          storyType: 'overnight',
          session_label: s.session_label,
          session_display_label,
          session_confidence: s.session_confidence ?? undefined,
          prob_move_ge_1pct: s.prob_move_ge_1pct ?? undefined,
          prob_move_ge_2pct: s.prob_move_ge_2pct ?? undefined,
          risk_confidence: s.risk_confidence ?? undefined,
          direction_bias: s.direction_bias ?? undefined,
          expected_abs_move_pct: s.expected_abs_move_pct ?? undefined,
          is_filing_related: s.is_filing_related,
          risk_drivers: s.risk_drivers?.length ? s.risk_drivers : undefined,
        };
      }
    );
    return mapped.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }, [overnightStories, getDateRange]);
  // Long Story tab: from backend GET /long-stories
  const longItems = useMemo(
    () =>
      longStories
        .map(
          (ls): NarrativeCluster => ({
            id: String(ls.id),
            title: ls.title ?? ls.canonical_theme ?? 'Long Story',
            summary: ls.summary ?? '',
            timestamp: ls.latest_article_published_at ?? ls.last_updated_at ?? ls.created_at ?? new Date().toISOString(),
            sentiment: 'Neutral',
            newsCount: ls.article_count ?? 0,
            sourceEvents: [],
            storylineId: Number(ls.id),
            storyType: 'long',
          })
        )
        .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()),
    [longStories]
  );
  const subtabItems = storylineSubtab === 'overnightImpact' ? overnightItems : longItems;

  const narrativeTimeline = useMemo(() => {
    if (!isCausalMode) return [];
    const rand = seededRandom(stock.symbol + "causal");
    const relevantNews = filteredNews.filter(() => rand() > 0.3);
    if (relevantNews.length === 0) return [];

    const clusters: NarrativeCluster[] = [];
    for (let i = 0; i < relevantNews.length; i += 2) {
      const group = relevantNews.slice(i, i + 2);
      const latest = group[0];
      const firstTitle = latest.title.split(' ').slice(0, 3).join(' ');
      const secondTitle = group[1] ? group[1].title.split(' ').slice(0, 3).join(' ') : 'Market Shifts';
      
      clusters.push({
        id: `cluster-${i}`,
        title: `Causal Narrative: ${firstTitle} and ${secondTitle} Core Signals`,
        summary: `AI Retrospective: The convergence of ${latest.category} data and corresponding industry signals between these events indicates a structural shift in ${stock.symbol}'s market position. This cluster effectively explains the subsequent volatility through a unified causal chain.`,
        timestamp: latest.timestamp,
        sentiment: latest.sentiment,
        newsCount: group.length,
        sourceEvents: group
      });
    }
    return clusters;
  }, [filteredNews, isCausalMode, stock.symbol]);

  const formatTimestamp = formatTimestampLocal;

  const getSentimentColor = (sentiment: string) => {
    switch (sentiment) {
      case 'Bullish': return '#CCFF00';
      case 'Bearish': return '#ff5000';
      default: return '#666666';
    }
  };

  const handleOpenNewsDetail = (news: NewsItem) => {
    setActiveDetailNarrative(null);
    setActiveDetailNews(news);
    // Load comment from localStorage
    const savedComment = localStorage.getItem(`news_comment_${news.id}`);
    setCurrentComment(savedComment || "");
  };

  const handleOpenNarrativeDetail = (narrative: NarrativeCluster) => {
    setActiveDetailNews(null);
    setLongStoryTimelineOpen(false);
    setActiveLongStoryId(null);
    setActiveDetailNarrative({ ...narrative, sourceEvents: narrative.sourceEvents || [] });
    setCurrentComment(userComments[narrative.id] || "");
    setExpandedFilingCitationId(null);
    setFormattedChunkErrorById({});
    const storylineId = narrative.storylineId ?? (typeof narrative.id === 'string' ? narrative.id : String(narrative.id));
    const storyIdStr = typeof narrative.id === 'string' ? narrative.id : String(narrative.id);
    const isOvernight = narrative.storyType === 'overnight';
    const isFiling = narrative.storyType === 'filing';

    if (isOvernight) {
      setSupportingArticlesStatus('loading');
      setFilingCitationsStatus('loading');
      setFilingCitations([]);
      Promise.all([
        fetch(`${API_BASE}/overnight-stories/${encodeURIComponent(storyIdStr)}/articles`).then((res) => (res.ok ? res.json() : Promise.reject(res))),
        fetch(`${API_BASE}/overnight-stories/${encodeURIComponent(storyIdStr)}/filing-chunks`).then((res) => (res.ok ? res.json() : Promise.reject(res))),
      ])
        .then(([articles, chunks]: [Array<{ id: number; ticker: string; title: string; summary?: string; url?: string; source?: string; published_at?: string; relation_type?: string }>, Array<{ chunk_id: string; filing_title: string; summary?: string; text: string; filing_url: string; form_type?: string; filed_date?: string; is_table?: boolean }>]) => {
          const events: SupportingArticle[] = (articles || []).map((a) => ({
            id: String(a.id),
            symbol: a.ticker,
            timestamp: a.published_at || new Date().toISOString(),
            category: 'Stock' as NewsCategory,
            source: a.source || 'Unknown',
            title: a.title,
            summary: a.summary || '',
            sentiment: 'Neutral' as SentimentType,
            url: a.url,
            relation_type: a.relation_type,
          }));
          setActiveDetailNarrative((prev) => (prev ? { ...prev, sourceEvents: events, newsCount: events.length } : null));
          setFilingCitations(Array.isArray(chunks) ? chunks : []);
          setSupportingArticlesStatus('loaded');
          setFilingCitationsStatus('loaded');
        })
        .catch(() => {
          setSupportingArticlesStatus('error');
          setFilingCitations([]);
          setFilingCitationsStatus('error');
          setActiveDetailNarrative((prev) => (prev ? { ...prev, sourceEvents: [], newsCount: 0 } : null));
        });
      return;
    }

    if (isFiling) {
      setFilingCitations([]);
      setFilingCitationsStatus('loading');
      setSupportingArticlesStatus('idle');
      if (storylineId != null && storylineId !== '') {
        fetch(`${API_BASE}/storylines/${encodeURIComponent(String(storylineId))}/filing-citations`)
          .then((res) => (res.ok ? res.json() : Promise.reject(res)))
          .then((data: Array<{ chunk_id: string; filing_title: string; summary?: string; text: string; filing_url: string; form_type?: string; filed_date?: string; is_table?: boolean }>) => {
            setFilingCitations(Array.isArray(data) ? data : []);
            setFilingCitationsStatus('loaded');
          })
          .catch(() => {
            setFilingCitations([]);
            setFilingCitationsStatus('error');
          });
      } else {
        setFilingCitationsStatus('idle');
      }
    } else {
      setFilingCitations([]);
      setFilingCitationsStatus('idle');
      if (storylineId != null && storylineId !== '') {
        setSupportingArticlesStatus('loading');
        fetch(`${API_BASE}/storylines/${encodeURIComponent(String(storylineId))}/articles`)
          .then((res) => (res.ok ? res.json() : Promise.reject(res)))
          .then((articles: Array<{ id: number; ticker: string; title: string; summary?: string; url?: string; source?: string; published_at?: string; relation_type?: string }>) => {
            const events: SupportingArticle[] = (articles || []).map((a) => ({
              id: String(a.id),
              symbol: a.ticker,
              timestamp: a.published_at || new Date().toISOString(),
              category: 'Stock' as NewsCategory,
              source: a.source || 'Unknown',
              title: a.title,
              summary: a.summary || '',
              sentiment: 'Neutral' as SentimentType,
              url: a.url,
              relation_type: a.relation_type,
            }));
            setActiveDetailNarrative((prev) => (prev ? { ...prev, sourceEvents: events, newsCount: events.length } : null));
            setSupportingArticlesStatus('loaded');
          })
          .catch(() => {
            setSupportingArticlesStatus('error');
            setActiveDetailNarrative((prev) => (prev ? { ...prev, sourceEvents: [], newsCount: 0 } : null));
          });
      } else {
        setSupportingArticlesStatus('idle');
      }
    }
  };

  const handleSaveComment = (id: string) => {
    // Save to localStorage
    if (currentComment.trim()) {
      localStorage.setItem(`news_comment_${id}`, currentComment);
    } else {
      localStorage.removeItem(`news_comment_${id}`);
    }
    setUserComments(prev => ({ ...prev, [id]: currentComment }));
  };

  const handleOpenLongStoryTimeline = (longStorylineId: string, title?: string) => {
    setActiveDetailNews(null);
    setActiveDetailNarrative(null);
    setLongStoryTimelineOpen(true);
    setActiveLongStoryId(longStorylineId);
    setLongStoryTimelineTitle(title || 'How the news evolves');
    setLongStoryTimeline(null);
    setLongStoryTimelineSummary('');
    setLongStoryTimelineTheme('');
    setLongStoryTotalArticles(0);
    setLongStoryTimelineLoading(true);
    fetch(`${API_BASE}/long-stories/${encodeURIComponent(longStorylineId)}/timeline`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data: { title?: string; summary?: string; theme?: string; total_articles?: number; months?: TimelineMonth[] }) => {
        setLongStoryTimeline(Array.isArray(data.months) ? data.months : []);
        setLongStoryTimelineTitle(data.title ?? title ?? 'How the news evolves');
        setLongStoryTimelineSummary(data.summary ?? '');
        setLongStoryTimelineTheme(data.theme ?? '');
        setLongStoryTotalArticles(data.total_articles ?? 0);
      })
      .catch(() => {
        setLongStoryTimeline([]);
        setLongStoryTotalArticles(0);
      })
      .finally(() => setLongStoryTimelineLoading(false));
  };

  const handleCloseLongStoryTimeline = () => {
    setLongStoryTimelineOpen(false);
    setLongStoryTimeline(null);
    setLongStoryTimelineTitle('');
    setLongStoryTimelineSummary('');
    setLongStoryTimelineTheme('');
    setLongStoryTotalArticles(0);
    setExpandedLongStoryArticleId(null);
  };

  const hasStorylineDetail = activeTab === 'Storyline' && (activeDetailNews || activeDetailNarrative || longStoryTimelineOpen);

  const handleCloseStorylineDetail = () => {
    setActiveDetailNews(null);
    setActiveDetailNarrative(null);
    setLongStoryTimelineOpen(false);
    setActiveLongStoryId(null);
    setLongStoryTimeline(null);
    setLongStoryTimelineTitle('');
    setLongStoryTimelineSummary('');
    setLongStoryTimelineTheme('');
    setExpandedSupportingId(null);
    setSupportingArticlesStatus('idle');
    setFilingCitations([]);
    setFilingCitationsStatus('idle');
    setExpandedFilingCitationId(null);
    setExpandedLongStoryArticleId(null);
  };

  return (
    <div className="flex min-h-0 h-[calc(100vh-125px)] relative overflow-hidden">
      {/* Detail Overlay (News) - only when not on Storyline; on Storyline we use split view; full width on mobile */}
      {activeTab !== 'Storyline' && activeDetailNews && (
        <div className="absolute right-0 top-0 bottom-0 w-full max-w-full md:w-[39%] bg-[#080808] z-[60] border-l border-gray-800 animate-in slide-in-from-right duration-300 shadow-[-20px_0_50px_rgba(0,0,0,0.8)] flex flex-col">
          <div className="p-4 border-b border-gray-900 flex items-center justify-between flex-shrink-0">
            <div className="flex items-center gap-2">
              <span 
                className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest"
                style={{ backgroundColor: `${CATEGORY_COLORS[activeDetailNews.category]}22`, color: CATEGORY_COLORS[activeDetailNews.category] }}
              >
                {activeDetailNews.category}
              </span>
              <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">{activeDetailNews.source}</span>
            </div>
            <button onClick={() => setActiveDetailNews(null)} className="p-1.5 hover:bg-gray-800 rounded-full transition-colors text-gray-500 hover:text-white">
              <X size={18} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 md:p-8 space-y-10 scrollbar-hide">
            <h2 className="text-2xl font-black leading-tight text-white">{activeDetailNews.title}</h2>
            
            {/* Published Date and Source */}
            <section>
              <div className="flex items-center gap-4 text-sm text-gray-400 mb-4">
                <span className="font-bold">{t('stockDetail.published')}:</span>
                <span>{formatTimestamp(activeDetailNews.timestamp)}</span>
              </div>
              {activeDetailNews.url && (
                <div className="mb-4">
                  <a 
                    href={activeDetailNews.url} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="text-[#CCFF00] hover:underline text-sm font-medium"
                  >
                    {t('stockDetail.viewOriginalArticle')} →
                  </a>
                </div>
              )}
            </section>

            {/* 1. Summary */}
            <section>
              <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('stockDetail.summary')}</h3>
              <p className="text-gray-400 text-sm leading-relaxed bg-[#0c0c0c] p-5 rounded-xl border border-gray-900">
                {activeDetailNews.summary || t('stockDetail.noSummaryAvailable')}
              </p>
            </section>

            {/* Macro-specific fields */}
            {activeDetailNews.category === 'Macro' && (
              <>
                {activeDetailNews.primaryTopic && (
                  <section>
                    <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('stockDetail.primaryTopic')}</h3>
                    <div className="bg-[#0c0c0c] p-4 rounded-xl border border-gray-900">
                      <span className="text-sm text-gray-300 font-medium">{activeDetailNews.primaryTopic}</span>
                    </div>
                  </section>
                )}
                {activeDetailNews.relatedTickers && activeDetailNews.relatedTickers.length > 0 && (
                  <section>
                    <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">Related Tickers</h3>
                    <div className="flex flex-wrap gap-2">
                      {activeDetailNews.relatedTickers.map((ticker) => (
                        <span 
                          key={ticker}
                          className="px-3 py-1 bg-[#0c0c0c] border border-gray-800 rounded-lg text-xs font-bold text-[#CCFF00]"
                        >
                          {ticker}
                        </span>
                      ))}
                    </div>
                  </section>
                )}
              </>
            )}

            {/* 2. AI Insight Analysis - Placeholder */}
            <section>
              <h3 className="text-[9px] font-black uppercase text-[#CCFF00] tracking-[0.2em] mb-3 flex items-center gap-2">
                <Sparkles size={10} /> {t('stockDetail.aiInsightAnalysis')}
              </h3>
              <div className="bg-[#CCFF00]/5 p-5 rounded-xl border border-[#CCFF00]/10">
                <p className="text-sm text-gray-400 leading-relaxed italic">
                  {t('stockDetail.aiInsightComingSoon')}
                </p>
              </div>
            </section>

            {/* 3. Sentiment Analysis - Placeholder */}
            <section>
               <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('stockDetail.sentimentAnalysis')}</h3>
               <div className="space-y-4">
                 <p className="text-[13px] text-gray-400 leading-relaxed italic">
                   {t('stockDetail.sentimentComingSoon')}
                 </p>
               </div>
            </section>

            {/* 4. Comments */}
            <section className="pb-10">
               <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3 flex items-center gap-2">
                <MessageSquare size={10} /> User Intelligence Log
              </h3>
              <textarea 
                value={currentComment}
                onChange={(e) => setCurrentComment(e.target.value)}
                placeholder="Log your causal reasoning..."
                className="w-full h-32 bg-black border border-gray-900 rounded-xl p-4 text-sm text-gray-300 outline-none focus:border-[#CCFF00] transition-colors resize-none mb-3"
              />
              <button 
                onClick={() => handleSaveComment(activeDetailNews.id)}
                className="w-full flex items-center justify-center gap-2 bg-[#CCFF00] text-black font-black uppercase text-[10px] tracking-widest py-3 rounded-full hover:bg-[#b8e600] active:scale-95 transition-all"
              >
                <Save size={12} /> {t('stockDetail.saveIntelligence')}
              </button>
            </section>
          </div>
        </div>
      )}

      {/* Detail Overlay (Narrative) - only when not on Storyline; on Storyline we use split view; full width on mobile */}
      {activeTab !== 'Storyline' && activeDetailNarrative && (
        <div className="absolute right-0 top-0 bottom-0 w-full max-w-full md:w-[39%] bg-[#080808] z-[60] border-l border-gray-800 animate-in slide-in-from-right duration-300 shadow-[-20px_0_50px_rgba(0,0,0,0.8)] flex flex-col">
           <div className="p-4 border-b border-gray-900 flex items-center justify-between flex-shrink-0">
            <div className="flex items-center gap-2">
              {activeDetailNarrative.storyType === 'overnight' ? (
                <>
                  <span className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest" style={{ backgroundColor: 'rgba(204, 255, 0, 0.15)', color: '#CCFF00' }}>{t('stockDetail.overnightImpact')}</span>
                  <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">
                    {activeDetailNarrative.direction_bias != null && <span style={{ color: getDirectionColor(activeDetailNarrative.direction_bias) }}>{activeDetailNarrative.direction_bias}</span>}
                    {activeDetailNarrative.expected_abs_move_pct != null && <span style={{ color: getDirectionColor(activeDetailNarrative.direction_bias) }}> · ~{Number(activeDetailNarrative.expected_abs_move_pct).toFixed(1)}%</span>}
                    {activeDetailNarrative.newsCount > 0 && <span> · {activeDetailNarrative.newsCount} {t('stockDetail.supportingArticles').toLowerCase()}</span>}
                  </span>
                </>
              ) : (
                <>
                  <span
                    className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest"
                    style={{ backgroundColor: `${getSentimentColor(activeDetailNarrative.sentiment)}22`, color: getSentimentColor(activeDetailNarrative.sentiment) }}
                  >
                    Synthetic Insight
                  </span>
                  <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Aggregating {activeDetailNarrative.newsCount} Events</span>
                </>
              )}
            </div>
            <button onClick={() => { setActiveDetailNarrative(null); setExpandedSupportingId(null); setSupportingArticlesStatus('idle'); setFilingCitations([]); setFilingCitationsStatus('idle'); setExpandedFilingCitationId(null); }} className="p-1.5 hover:bg-gray-800 rounded-full transition-colors text-gray-500 hover:text-white">
              <X size={18} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 md:p-8 space-y-10 scrollbar-hide">
            <h2 className="text-2xl font-black leading-tight text-white">{activeDetailNarrative.title}</h2>
            
            {/* 1. Supporting content: filing citations (SEC Insight) or articles (short/long) */}
            <section>
              <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">
                {activeDetailNarrative.storyType === 'filing' ? t('stockDetail.secFilingExcerpts') : activeDetailNarrative.storylineId ? t('stockDetail.supportingArticles') : t('stockDetail.constituentEvidence')}
              </h3>
              <div className="space-y-8">
                {activeDetailNarrative.storyType === 'filing' ? (
                  <>
                    {filingCitationsStatus === 'loading' && (
                      <p className="text-[11px] text-gray-500 italic">{t('stockDetail.loadingFilingExcerpts')}</p>
                    )}
                    {filingCitationsStatus === 'error' && (
                      <p className="text-[11px] text-amber-500/90 italic">{t('stockDetail.noFilingExcerpts')}</p>
                    )}
                    {filingCitationsStatus === 'loaded' && filingCitations.length === 0 && (
                      <p className="text-[11px] text-gray-500 italic">{t('stockDetail.noFilingExcerptsForInsight')}</p>
                    )}
                    {filingCitationsStatus === 'loaded' && filingCitations.map((cit, idx) => {
                      const isExpanded = expandedFilingCitationId === cit.chunk_id;
                      const hasText = !!cit.text?.trim();
                      const hasSummary = !!cit.summary?.trim();
                      const title = cit.filing_title ?? (cit.form_type ? `${cit.form_type} excerpt` : `Excerpt ${idx + 1}`);
                      const formatted = formattedChunkByCitationId[cit.chunk_id];
                      const formatting = formattedChunkLoadingById[cit.chunk_id];
                      const formatError = formattedChunkErrorById[cit.chunk_id];
                      const displayText = formatted ?? cit.text;
                      const looksLikeMarkdownTable = (s: string) => /\|.+\|/.test(s) && (s.includes('---') || s.split('\n').filter(l => l.includes('|')).length >= 2);
                      const renderTable = (raw: string) => {
                        const lines = raw.trim().split('\n').filter(Boolean);
                        const sep = lines.some(l => l.includes('|')) ? '|' : '\t';
                        const parsed = lines.map(l => l.split(sep).map(c => c.trim()));
                        const isSeparatorRow = (cells: string[]) => cells.length > 0 && cells.every(c => /^[\s\-]*$/.test(c));
                        const dataRows = parsed.filter(row => row.length > 0 && !isSeparatorRow(row));
                        if (dataRows.length === 0) return <p className="mt-3 text-[11px] text-gray-500 whitespace-pre-wrap border-t border-gray-800 pt-3">{raw}</p>;
                        const numCols = Math.max(...dataRows.map(r => r.length));
                        const padRow = (row: string[]) => [...row, ...Array(Math.max(0, numCols - row.length)).fill('')];
                        const header = dataRows[0];
                        const body = dataRows.slice(1);
                        return (
                          <div className="mt-3 overflow-x-auto border-t border-gray-800 pt-3">
                            <table className="w-full min-w-[200px] text-[11px] text-gray-500 border-collapse">
                              <thead>
                                <tr>
                                  {padRow(header).map((cell, j) => (
                                    <th key={j} className="px-2 py-1.5 border border-gray-700 bg-gray-900/50 text-gray-400 text-left font-semibold">{cell || '\u00a0'}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {body.map((row, i) => (
                                  <tr key={i}>
                                    {padRow(row).map((cell, j) => (
                                      <td key={j} className="px-2 py-1 border border-gray-800 align-top">{cell || '\u00a0'}</td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        );
                      };
                      const renderFormattedChunk = (text: string) =>
                        looksLikeMarkdownTable(text) ? renderTable(text) : (
                          <p className="text-[11px] text-gray-500 leading-relaxed whitespace-pre-wrap">{text}</p>
                        );
                      return (
                        <div key={cit.chunk_id} className="relative flex items-start group">
                          <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight transition-colors group-hover:text-gray-400">
                            {cit.filed_date ?? '—'}
                          </div>
                          <div className="absolute left-[110px] top-2 -translate-x-1/2 w-2.5 h-2.5 rounded-full border border-black z-10 bg-gray-600 group-hover:bg-[#CCFF00] transition-all" />
                          <div className="flex-1 pl-4 md:pl-12 pr-4">
                            <div className="p-4 bg-[#0c0c0c] border border-gray-900 rounded-xl hover:border-gray-700 transition-all flex items-start gap-3">
                              <button
                                type="button"
                                onClick={() => setExpandedFilingCitationId((id) => (id === cit.chunk_id ? null : cit.chunk_id))}
                                className="flex-shrink-0 p-0.5 rounded hover:bg-gray-800 text-gray-700 group-hover:text-[#CCFF00] transition-all"
                                title={hasText ? (isExpanded ? t('stockDetail.hideFullExcerpt') : t('stockDetail.showFullExcerpt')) : hasSummary ? t('stockDetail.summaryOnly') : t('stockDetail.noText')}
                                disabled={!hasText && !hasSummary}
                              >
                                <ChevronRight size={14} className={`mt-0.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                              </button>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center justify-between gap-2 mb-1">
                                  <span className="text-[8px] font-black text-gray-600 uppercase">{title}</span>
                                  {cit.form_type ? (
                                    <span className="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-wider bg-gray-800 text-gray-400 flex-shrink-0">
                                      {cit.form_type}
                                    </span>
                                  ) : null}
                                </div>
                                {hasSummary && (
                                  <p className="text-[11px] text-gray-300 leading-relaxed">
                                    {cit.summary}
                                  </p>
                                )}
                                {hasText && isExpanded && (
                                  <div className={hasSummary ? 'mt-3 border-t border-gray-800 pt-3' : ''}>
                                    {formatting && (
                                      <p className="text-[11px] text-gray-500 italic">Formatting for readability…</p>
                                    )}
                                    {!formatting && (formatted ?? formatError) && (
                                      <>
                                        {formatError && (
                                          <p className="text-[11px] text-amber-500/90 italic mb-2">Formatting failed; showing raw excerpt.</p>
                                        )}
                                        {renderFormattedChunk(displayText)}
                                      </>
                                    )}
                                    {!formatting && !formatted && !formatError && (
                                      renderFormattedChunk(cit.text)
                                    )}
                                  </div>
                                )}
                                {!hasSummary && hasText && !isExpanded && (
                                  <p className="mt-1 text-[11px] text-gray-500 italic">Expand to view {cit.is_table ? 'table' : 'excerpt'}</p>
                                )}
                                {cit.filing_url && (hasSummary || hasText) && (
                                  <a
                                    href={cit.filing_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    onClick={(e) => e.stopPropagation()}
                                    className="mt-2 inline-block text-[#CCFF00] hover:underline text-[11px] font-medium"
                                  >
                                    View full filing →
                                  </a>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </>
                ) : (
                  <>
                    {activeDetailNarrative.storylineId != null && activeDetailNarrative.sourceEvents.length === 0 && (
                      <>
                        {supportingArticlesStatus === 'loading' && (
                          <p className="text-[11px] text-gray-500 italic">{t('stockDetail.loadingSupportingArticles')}</p>
                        )}
                        {supportingArticlesStatus === 'error' && (
                          <p className="text-[11px] text-amber-500/90 italic">{t('stockDetail.supportArticlesError')}</p>
                        )}
                        {supportingArticlesStatus === 'loaded' && (
                          <p className="text-[11px] text-gray-500 italic">{t('stockDetail.noSupportingArticles')}</p>
                        )}
                      </>
                    )}
                    {activeDetailNarrative.sourceEvents.map((ev) => {
                      const isExpanded = expandedSupportingId === ev.id;
                      const hasSummary = !!ev.summary?.trim();
                      return (
                        <div key={ev.id} className="relative flex items-start group">
                          <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight transition-colors group-hover:text-gray-400">
                            {formatTimestamp(ev.timestamp)}
                          </div>
                          <div className="absolute left-[110px] top-2 -translate-x-1/2 w-2.5 h-2.5 rounded-full border border-black z-10 bg-gray-600 group-hover:bg-[#CCFF00] transition-all" />
                          <div className="flex-1 pl-4 md:pl-12 pr-4">
                            <div className="p-4 bg-[#0c0c0c] border border-gray-900 rounded-xl hover:border-gray-700 transition-all flex items-start gap-3">
                              <button
                                type="button"
                                onClick={(e) => { e.stopPropagation(); setExpandedSupportingId((id) => (id === ev.id ? null : ev.id)); }}
                                className="flex-shrink-0 p-0.5 rounded hover:bg-gray-800 text-gray-700 group-hover:text-[#CCFF00] transition-all"
                                title={hasSummary ? (isExpanded ? t('stockDetail.hideSummary') : t('stockDetail.showSummary')) : t('stockDetail.noSummary')}
                                disabled={!hasSummary}
                              >
                                <ChevronRight size={14} className={`mt-0.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                              </button>
                              {ev.url ? (
                                <a
                                  href={ev.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="flex-1 min-w-0 cursor-pointer hover:underline underline-offset-2 decoration-[#CCFF00]/60"
                                >
                                  <div className="flex items-center justify-between gap-2 mb-1">
                                    <span className="text-[8px] font-black text-gray-600 uppercase">{ev.source}</span>
                                    {ev.relation_type ? (
                                      <span className="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-wider bg-gray-800 text-gray-400 flex-shrink-0">
                                        {ev.relation_type.replace(/_/g, ' ')}
                                      </span>
                                    ) : null}
                                  </div>
                                  <span className="text-[11px] font-bold text-gray-400 hover:text-[#CCFF00] leading-tight block transition-colors">
                                    {ev.title}
                                  </span>
                                  {hasSummary && isExpanded && (
                                    <p className="mt-3 text-[11px] text-gray-500 leading-relaxed border-t border-gray-800 pt-3">
                                      {ev.summary}
                                    </p>
                                  )}
                                </a>
                              ) : (
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center justify-between gap-2 mb-1">
                                    <span className="text-[8px] font-black text-gray-600 uppercase">{ev.source}</span>
                                    {ev.relation_type ? (
                                      <span className="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-wider bg-gray-800 text-gray-400 flex-shrink-0">
                                        {ev.relation_type.replace(/_/g, ' ')}
                                      </span>
                                    ) : null}
                                  </div>
                                  <h4 className="text-[11px] font-bold text-gray-400 group-hover:text-white leading-tight">{ev.title}</h4>
                                  {hasSummary && isExpanded && (
                                    <p className="mt-3 text-[11px] text-gray-500 leading-relaxed border-t border-gray-800 pt-3">
                                      {ev.summary}
                                    </p>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </>
                )}
              </div>
            </section>

            {/* 2. Narrative Synthesis */}
            <section>
              <h3 className="text-[9px] font-black uppercase text-[#CCFF00] tracking-[0.2em] mb-3 flex items-center gap-2">
                <Sparkles size={10} /> {t('stockDetail.aiNarrativeSynthesis')}
              </h3>
              <div className="bg-[#CCFF00]/5 p-5 rounded-xl border border-[#CCFF00]/10">
                <p className="text-sm text-gray-200 leading-relaxed italic">
                  {activeDetailNarrative.summary}
                </p>
              </div>
            </section>
          </div>
        </div>
      )}

      {/* Long-story timeline overlay (by month); full width on mobile */}

      {/* Content: full width (Market Feed / Categories / Timeframe / Insight Depth removed; Macro has its own tab) */}
      <div className="flex-1 min-w-0 flex flex-col bg-black relative">
        <div className="px-4 sm:px-6 md:px-8 border-b border-gray-900 bg-black flex items-center justify-between h-[50px] flex-shrink-0">
          <div className="flex items-center gap-4 md:gap-8 h-full">
            {(['Storyline', 'Price Impact'] as RightTab[]).map(tab => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`h-full text-xs font-black uppercase tracking-[0.15em] transition-all border-b-2 ${activeTab === tab ? 'border-white text-white' : 'border-transparent text-gray-600 hover:text-gray-400'}`}
              >
                {tab === 'Storyline' ? t('stockDetail.storyline') : t('stockDetail.priceImpact')}
              </button>
            ))}
          </div>

        </div>

        <div className={`flex-1 min-h-0 flex flex-col ${hasStorylineDetail ? 'overflow-hidden' : 'overflow-y-auto p-4 sm:p-6 md:p-8 scroll-smooth'}`}>
          <div className={hasStorylineDetail ? 'flex flex-col md:flex-row flex-1 min-h-0 min-w-0' : activeTab === 'Price Impact' ? 'w-full' : 'max-w-4xl mx-auto'}>
            {activeTab === 'Storyline' ? (
              hasStorylineDetail ? (
                <>
                  {/* Left: list – desktop always; on mobile hidden when article open so article is full-screen */}
                  <div className={`w-full md:w-[min(420px,40%)] md:min-w-[300px] flex-shrink-0 overflow-y-auto border-r-0 md:border-r border-gray-800 p-4 sm:p-6 animate-in fade-in duration-200 max-h-[45vh] md:max-h-none ${hasStorylineDetail ? 'hidden md:block' : ''}`}>
                    <NewsFilterPanel
                      selectedTimeframe={selectedTimeframe}
                      customRange={customRange}
                      onTimeframeChange={setSelectedTimeframe}
                      onCustomRangeChange={setCustomRange}
                    />
                    {loadingStorylines && selectedCategories.includes('Stock') && <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-6">{t('stockDetail.loadingStorylines')}</div>}
                    {loadingMacroNews && selectedCategories.includes('Macro') && <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-6">{t('stockDetail.loadingMacroNews')}</div>}
                    {selectedCategories.includes('Stock') && (
                      <div className="flex items-center gap-2 mb-6">
                        <button onClick={() => setStorylineSubtab('overnightImpact')} className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold transition-colors ${storylineSubtab === 'overnightImpact' ? 'bg-[#CCFF00] text-black' : 'bg-[#121212] text-gray-400 hover:text-white border border-gray-800'}`}>{t('stockDetail.overnightImpact')}</button>
                        <button onClick={() => setStorylineSubtab('longStory')} className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold transition-colors ${storylineSubtab === 'longStory' ? 'bg-[#CCFF00] text-black' : 'bg-[#121212] text-gray-400 hover:text-white border border-gray-800'}`}>{t('stockDetail.longStory')}</button>
                      </div>
                    )}
                    <div className="space-y-16 pr-2">
                      {selectedCategories.includes('Stock') ? (storylineSubtab === 'overnightImpact'
                        ? (overnightItems.length > 0 ? (
                            <>
                              {overnightItems.map((narrative) => {
                                const impactColor = getSentimentColor(narrative.sentiment);
                                const isLong = narrative.storyType === 'long';
                                const isFiling = narrative.storyType === 'filing';
                                const isOvernight = narrative.storyType === 'overnight';
                                const directionColor = getDirectionColor(narrative.direction_bias);
                                const hasAnyRisk = isOvernight && (narrative.expected_abs_move_pct != null || narrative.direction_bias != null);
                                return (
                                  <div key={narrative.id} className="relative flex items-start group">
                                    <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight">{formatTimestamp(narrative.timestamp)}</div>
                                    <div className="absolute left-[110px] top-2 -translate-x-1/2 w-3.5 h-3.5 rounded-full border-2 border-black z-10 transition-all duration-300 group-hover:scale-125 shadow-[0_0_10px_rgba(204,255,0,0.4)] flex items-center justify-center" style={{ backgroundColor: impactColor }}><Sparkles size={8} className="text-black" /></div>
                                    <div onClick={() => isLong ? handleOpenLongStoryTimeline(narrative.id, narrative.title) : handleOpenNarrativeDetail(narrative)} className="flex-1 pl-4 md:pl-12 pr-4 bg-[#0a0a0a]/50 p-6 rounded-xl border transition-all cursor-pointer hover:border-gray-700" style={{ borderLeft: `2px solid ${impactColor}` }}>
                                      <div className="flex items-center gap-3 mb-2 flex-wrap">
                                        <span className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest" style={{ backgroundColor: isFiling ? 'rgba(59, 130, 246, 0.15)' : (isOvernight || isLong) ? 'rgba(204, 255, 0, 0.15)' : `${impactColor}22`, color: isFiling ? '#3b82f6' : (isOvernight || isLong) ? '#CCFF00' : impactColor }}>{isFiling ? t('stockDetail.secInsight') : isLong ? t('stockDetail.longStory') : isOvernight ? (narrative.session_display_label === 'Intraday' ? t('stockDetail.intraday') : narrative.session_display_label === 'Mixed' ? t('stockDetail.mixed') : t('stockDetail.overnight')) : t('stockDetail.stockStory')}</span>
                                        {isOvernight && narrative.is_filing_related && (
                                          <span className="px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider text-[#3b82f6] border border-[#3b82f6]/50">{t('stockDetail.linkedToSecFiling')}</span>
                                        )}
                                        {isOvernight && (
                                          <span className="text-[9px] font-bold text-gray-500 uppercase tracking-wider">
                                            {hasAnyRisk ? (
                                              <>
                                                {narrative.direction_bias != null && <span style={{ color: directionColor }}>{narrative.direction_bias}</span>}
                                                {narrative.expected_abs_move_pct != null && <span style={{ color: directionColor }}> · ~{Number(narrative.expected_abs_move_pct).toFixed(1)}%</span>}
                                              </>
                                            ) : (
                                              <span>{t('stockDetail.riskLabel')}: —</span>
                                            )}
                                          </span>
                                        )}
                                        {(narrative.storyType === 'short' || narrative.storyType === 'long') && insightMap[narrative.id] && <button type="button" onClick={(e) => { e.stopPropagation(); handleOpenNarrativeDetail(insightMap[narrative.id]); }} className="flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest border border-gray-700 text-gray-400 hover:border-[#3b82f6] hover:text-[#3b82f6] transition-colors"><Sparkles size={10} /> {t('stockDetail.insight')}</button>}
                                      </div>
                                      <h4 className={`text-lg font-bold mb-3 leading-snug transition-colors ${(activeDetailNews || activeDetailNarrative || (longStoryTimelineOpen && activeLongStoryId === narrative.id)) && (activeDetailNarrative?.id === narrative.id || activeDetailNews?.id === narrative.id || (longStoryTimelineOpen && activeLongStoryId === narrative.id)) ? 'text-[#CCFF00]' : 'text-gray-100 group-hover:text-[#CCFF00]'}`}>{narrative.title}</h4>
                                      <p className="text-sm text-gray-400 leading-relaxed font-medium italic line-clamp-2">"{narrative.summary}"</p>
                                      <div className="mt-5"><button className="text-[9px] font-black text-gray-700 uppercase tracking-[0.2em] group-hover:text-[#CCFF00] transition-colors flex items-center gap-1">{t('stockDetail.viewSupportingArticles')} <span className="text-lg leading-none mb-0.5">→</span></button></div>
                                    </div>
                                  </div>
                                );
                              })}
                            </>
                          ) : (
                        <div className="py-20 text-center space-y-2">
                          <p className="text-gray-500 text-sm font-medium">{t('stockDetail.noOvernightStories')}</p>
                        </div>
                          ))
                        : (subtabItems.length > 0 ? subtabItems.map((narrative) => {
                        const impactColor = getSentimentColor(narrative.sentiment);
                        const isLong = narrative.storyType === 'long';
                        const isFiling = narrative.storyType === 'filing';
                        const isOvernight = narrative.storyType === 'overnight';
                        const directionColor = getDirectionColor(narrative.direction_bias);
                        const hasAnyRisk = isOvernight && (narrative.expected_abs_move_pct != null || narrative.direction_bias != null);
                        return (
                          <div key={narrative.id} className="relative flex items-start group">
                            <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight">{formatTimestamp(narrative.timestamp)}</div>
                            <div className="absolute left-[110px] top-2 -translate-x-1/2 w-3.5 h-3.5 rounded-full border-2 border-black z-10 transition-all duration-300 group-hover:scale-125 shadow-[0_0_10px_rgba(204,255,0,0.4)] flex items-center justify-center" style={{ backgroundColor: impactColor }}><Sparkles size={8} className="text-black" /></div>
                            <div onClick={() => isLong ? handleOpenLongStoryTimeline(narrative.id, narrative.title) : handleOpenNarrativeDetail(narrative)} className="flex-1 pl-4 md:pl-12 pr-4 bg-[#0a0a0a]/50 p-6 rounded-xl border transition-all cursor-pointer hover:border-gray-700" style={{ borderLeft: `2px solid ${impactColor}` }}>
                              <div className="flex items-center gap-3 mb-2 flex-wrap">
                                <span className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest" style={{ backgroundColor: isFiling ? 'rgba(59, 130, 246, 0.15)' : (isOvernight || isLong) ? 'rgba(204, 255, 0, 0.15)' : `${impactColor}22`, color: isFiling ? '#3b82f6' : (isOvernight || isLong) ? '#CCFF00' : impactColor }}>{isFiling ? t('stockDetail.secInsight') : isLong ? t('stockDetail.longStory') : isOvernight ? (narrative.session_display_label === 'Intraday' ? t('stockDetail.intraday') : narrative.session_display_label === 'Mixed' ? t('stockDetail.mixed') : t('stockDetail.overnight')) : t('stockDetail.stockStory')}</span>
                                {isOvernight && narrative.is_filing_related && (
                                  <span className="px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider text-[#3b82f6] border border-[#3b82f6]/50">{t('stockDetail.linkedToSecFiling')}</span>
                                )}
                                {isOvernight && (
                                  <span className="text-[9px] font-bold text-gray-500 uppercase tracking-wider">
                                    {hasAnyRisk ? (
                                      <>
                                        {narrative.direction_bias != null && <span style={{ color: directionColor }}>{narrative.direction_bias}</span>}
                                        {narrative.expected_abs_move_pct != null && <span style={{ color: directionColor }}> · ~{Number(narrative.expected_abs_move_pct).toFixed(1)}%</span>}
                                      </>
                                    ) : (
                                      <span>{t('stockDetail.riskLabel')}: —</span>
                                    )}
                                  </span>
                                )}
                                {(narrative.storyType === 'short' || narrative.storyType === 'long') && insightMap[narrative.id] && <button type="button" onClick={(e) => { e.stopPropagation(); handleOpenNarrativeDetail(insightMap[narrative.id]); }} className="flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest border border-gray-700 text-gray-400 hover:border-[#3b82f6] hover:text-[#3b82f6] transition-colors"><Sparkles size={10} /> {t('stockDetail.insight')}</button>}
                              </div>
                              <h4 className={`text-lg font-bold mb-3 leading-snug transition-colors ${(activeDetailNews || activeDetailNarrative || (longStoryTimelineOpen && activeLongStoryId === narrative.id)) && (activeDetailNarrative?.id === narrative.id || activeDetailNews?.id === narrative.id || (longStoryTimelineOpen && activeLongStoryId === narrative.id)) ? 'text-[#CCFF00]' : 'text-gray-100 group-hover:text-[#CCFF00]'}`}>{narrative.title}</h4>
                              <p className="text-sm text-gray-400 leading-relaxed font-medium italic line-clamp-2">"{narrative.summary}"</p>
                              <div className="mt-5"><button className="text-[9px] font-black text-gray-700 uppercase tracking-[0.2em] group-hover:text-[#CCFF00] transition-colors flex items-center gap-1">{t('stockDetail.viewSupportingArticles')} <span className="text-lg leading-none mb-0.5">→</span></button></div>
                            </div>
                          </div>
                        );
                      }) : (
                        <div className="py-20 text-center space-y-2">
                          <p className="text-gray-500 text-sm font-medium">
                            {storylineSubtab === 'longStory' && longStoriesFetchError
                              ? t('stockDetail.longStoriesLoadError')
                              : storylineSubtab === 'overnightImpact'
                                ? t('stockDetail.noOvernightStories')
                                : storylineSubtab === 'longStory'
                                  ? t('stockDetail.noLongStories')
                                  : t('stockDetail.noSecInsights')}
                          </p>
                          {storylineSubtab === 'longStory' && !longStoriesFetchError && (
                            <p className="text-gray-600 text-xs max-w-sm mx-auto">{t('stockDetail.longStoriesEmptyHint')}</p>
                          )}
                        </div>
                      ))) : isCausalMode ? narrativeTimeline.map((narrative) => {
                        const impactColor = getSentimentColor(narrative.sentiment);
                        return (
                          <div key={narrative.id} className="relative flex items-start group">
                            <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight">{formatTimestamp(narrative.timestamp)}</div>
                            <div className="absolute left-[110px] top-2 -translate-x-1/2 w-3.5 h-3.5 rounded-full border-2 border-black z-10 transition-all duration-300 group-hover:scale-125 shadow-[0_0_10px_rgba(204,255,0,0.4)] flex items-center justify-center" style={{ backgroundColor: impactColor }}><Sparkles size={8} className="text-black" /></div>
                            <div onClick={() => handleOpenNarrativeDetail(narrative)} className="flex-1 pl-4 md:pl-12 pr-4 bg-[#0a0a0a]/50 p-6 rounded-xl border transition-all cursor-pointer hover:border-gray-700" style={{ borderLeft: `2px solid ${impactColor}` }}>
                              <div className="flex items-center gap-3 mb-2">
                                <span className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest" style={{ backgroundColor: `${impactColor}22`, color: impactColor }}>{t('stockDetail.syntheticInsight')}</span>
                                <span className="text-[9px] font-bold text-gray-600 uppercase tracking-widest">{t('stockDetail.aggregatingEvents', { count: narrative.newsCount })}</span>
                              </div>
                              <h4 className={`text-lg font-bold mb-3 leading-snug transition-colors ${activeDetailNarrative?.id === narrative.id ? 'text-[#CCFF00]' : 'text-gray-100 group-hover:text-[#CCFF00]'}`}>{narrative.title}</h4>
                              <p className="text-sm text-gray-400 leading-relaxed font-medium italic line-clamp-2">"{narrative.summary}"</p>
                              <div className="mt-5 flex items-center justify-between">
                                <button className="text-[9px] font-black text-gray-700 uppercase tracking-[0.2em] group-hover:text-[#CCFF00] transition-colors flex items-center gap-1">{t('stockDetail.deconstructEvidence')} <span className="text-lg leading-none mb-0.5">→</span></button>
                                <div className="flex items-center gap-2">
                                  <span className="text-[10px] font-bold text-gray-600 uppercase tracking-widest">Historical Impact:</span>
                                  <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: impactColor }}>{narrative.sentiment}</span>
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      }) : filteredNews.map((news) => (
                        <div key={news.id} className="relative flex items-start group">
                          <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight">{formatTimestamp(news.timestamp)}</div>
                          <div className="absolute left-[110px] top-2 -translate-x-1/2 w-2.5 h-2.5 rounded-full border border-black z-10 transition-all duration-300 group-hover:scale-150 ring-4 ring-black" style={{ backgroundColor: getSentimentColor(news.sentiment) }} />
                          <div onClick={() => handleOpenNewsDetail(news)} className="flex-1 pl-4 md:pl-12 pr-4 cursor-pointer">
                            <div className="flex items-center gap-3 mb-2">
                              <span className="px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider" style={{ backgroundColor: `${CATEGORY_COLORS[news.category]}22`, color: CATEGORY_COLORS[news.category] }}>{news.category}</span>
                              <span className="text-[10px] font-semibold text-gray-600 tracking-wide uppercase">{news.source}</span>
                            </div>
                            <h4 className={`text-base font-bold mb-3 leading-snug transition-colors ${activeDetailNews?.id === news.id ? 'text-[#CCFF00]' : 'text-gray-100 group-hover:text-[#CCFF00]'}`}>{news.title}</h4>
                            <p className="text-[13px] text-gray-500 leading-relaxed font-medium">{news.summary}</p>
                            <div className="mt-5"><button className="text-[9px] font-black text-gray-700 uppercase tracking-[0.2em] hover:text-[#CCFF00] transition-colors flex items-center gap-1">{t('stockDetail.exploreNarrative')} <span className="text-lg leading-none mb-0.5">→</span></button></div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                  {/* Right: opened article – flex-1 min-h-0 so inner overflow-y-auto can scroll to bottom on mobile */}
                  <div ref={storylineDetailPanelRef} className="flex-1 min-w-0 min-h-0 flex flex-col bg-[#080808] md:border-l border-gray-800 overflow-hidden">
                    {/* Mobile only: back to list so user can return to title page */}
                    {hasStorylineDetail && (
                      <div className="flex md:hidden p-4 border-b border-gray-900 flex-shrink-0">
                        <button type="button" onClick={handleCloseStorylineDetail} className="flex items-center gap-2 text-gray-400 hover:text-white transition-colors">
                          <ArrowLeft size={20} />
                          <span className="text-sm font-bold uppercase tracking-wider">{t('stockDetail.backToList')}</span>
                        </button>
                      </div>
                    )}
                    {activeDetailNews && (
                      <>
                        <div className="p-4 border-b border-gray-900 flex items-center justify-between flex-shrink-0">
                          <div className="flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest" style={{ backgroundColor: `${CATEGORY_COLORS[activeDetailNews.category]}22`, color: CATEGORY_COLORS[activeDetailNews.category] }}>{activeDetailNews.category}</span>
                            <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">{activeDetailNews.source}</span>
                          </div>
                          <button onClick={() => setActiveDetailNews(null)} className="p-1.5 hover:bg-gray-800 rounded-full transition-colors text-gray-500 hover:text-white"><X size={18} /></button>
                        </div>
                        <div className="flex-1 min-h-0 overflow-y-auto p-4 sm:p-6 md:p-8 space-y-10 scrollbar-hide">
                          <h2 className="text-2xl font-black leading-tight text-white">{activeDetailNews.title}</h2>
                          <section><div className="flex items-center gap-4 text-sm text-gray-400 mb-4"><span className="font-bold">{t('stockDetail.published')}:</span><span>{formatTimestamp(activeDetailNews.timestamp)}</span></div>{activeDetailNews.url && <div className="mb-4"><a href={activeDetailNews.url} target="_blank" rel="noopener noreferrer" className="text-[#CCFF00] hover:underline text-sm font-medium">{t('stockDetail.viewOriginalArticle')} →</a></div>}</section>
                          <section><h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('stockDetail.summary')}</h3><p className="text-gray-400 text-sm leading-relaxed bg-[#0c0c0c] p-5 rounded-xl border border-gray-900">{activeDetailNews.summary || t('stockDetail.noSummaryAvailable')}</p></section>
                          {activeDetailNews.category === 'Macro' && (<>{(activeDetailNews as NewsItem & { primaryTopic?: string }).primaryTopic && <section><h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('stockDetail.primaryTopic')}</h3><div className="bg-[#0c0c0c] p-4 rounded-xl border border-gray-900"><span className="text-sm text-gray-300 font-medium">{(activeDetailNews as NewsItem & { primaryTopic?: string }).primaryTopic}</span></div></section>}{(activeDetailNews as NewsItem & { relatedTickers?: string[] }).relatedTickers?.length ? <section><h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">Related Tickers</h3><div className="flex flex-wrap gap-2">{(activeDetailNews as NewsItem & { relatedTickers?: string[] }).relatedTickers!.map((ticker) => <span key={ticker} className="px-3 py-1 bg-[#0c0c0c] border border-gray-800 rounded-lg text-xs font-bold text-[#CCFF00]">{ticker}</span>)}</div></section> : null}</>)}
                          <section><h3 className="text-[9px] font-black uppercase text-[#CCFF00] tracking-[0.2em] mb-3 flex items-center gap-2"><Sparkles size={10} /> {t('stockDetail.aiInsightAnalysis')}</h3><div className="bg-[#CCFF00]/5 p-5 rounded-xl border border-[#CCFF00]/10"><p className="text-sm text-gray-400 leading-relaxed italic">{t('stockDetail.aiInsightComingSoon')}</p></div></section>
                          <section><h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('stockDetail.sentimentAnalysis')}</h3><div className="space-y-4"><p className="text-[13px] text-gray-400 leading-relaxed italic">{t('stockDetail.sentimentComingSoon')}</p></div></section>
                          <section className="pb-10"><h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3 flex items-center gap-2"><MessageSquare size={10} /> {t('stockDetail.userIntelligenceLog')}</h3><textarea value={currentComment} onChange={(e) => setCurrentComment(e.target.value)} placeholder={t('stockDetail.logReasoningPlaceholder')} className="w-full h-32 bg-black border border-gray-900 rounded-xl p-4 text-sm text-gray-300 outline-none focus:border-[#CCFF00] transition-colors resize-none mb-3" /><button onClick={() => handleSaveComment(activeDetailNews.id)} className="w-full flex items-center justify-center gap-2 bg-[#CCFF00] text-black font-black uppercase text-[10px] tracking-widest py-3 rounded-full hover:bg-[#b8e600] active:scale-95 transition-all"><Save size={12} /> {t('stockDetail.saveIntelligence')}</button></section>
                        </div>
                      </>
                    )}
                    {activeDetailNarrative && (
                      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
                        <div className="p-4 border-b border-gray-900 flex items-center justify-between flex-shrink-0">
                          <div className="flex items-center gap-2">
                            {activeDetailNarrative.storyType === 'overnight' ? (
                              <>
                                <span className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest" style={{ backgroundColor: 'rgba(204, 255, 0, 0.15)', color: '#CCFF00' }}>{t('stockDetail.overnightImpact')}</span>
                                <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wider">
                                  {activeDetailNarrative.direction_bias != null && (
                                    <span style={{ color: getDirectionColor(activeDetailNarrative.direction_bias) }}>{activeDetailNarrative.direction_bias}</span>
                                  )}
                                  {activeDetailNarrative.expected_abs_move_pct != null && <span style={{ color: getDirectionColor(activeDetailNarrative.direction_bias) }}> · ~{Number(activeDetailNarrative.expected_abs_move_pct).toFixed(1)}%</span>}
                                  {activeDetailNarrative.newsCount > 0 && <span> · {activeDetailNarrative.newsCount} {t('stockDetail.supportingArticles').toLowerCase()}</span>}
                                </span>
                              </>
                            ) : (
                              <>
                                <span className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest" style={{ backgroundColor: `${getSentimentColor(activeDetailNarrative.sentiment)}22`, color: getSentimentColor(activeDetailNarrative.sentiment) }}>Synthetic Insight</span>
                                <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Aggregating {activeDetailNarrative.newsCount} Events</span>
                              </>
                            )}
                          </div>
                          <button onClick={() => { setActiveDetailNarrative(null); setExpandedSupportingId(null); setSupportingArticlesStatus('idle'); setFilingCitations([]); setFilingCitationsStatus('idle'); setExpandedFilingCitationId(null); }} className="p-1.5 hover:bg-gray-800 rounded-full transition-colors text-gray-500 hover:text-white"><X size={18} /></button>
                        </div>
                        <div className="flex-1 overflow-y-auto p-4 sm:p-6 md:p-8 pb-16 md:pb-8 space-y-10 scrollbar-hide min-h-0">
                          <h2 className="text-2xl font-black leading-tight text-white">{activeDetailNarrative.title}</h2>
                          {activeDetailNarrative.storyType === 'overnight' ? (
                            <>
                              {/* 1. Overnight risk / prediction */}
                              <section>
                                <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('stockDetail.overnightRisk')}</h3>
                                <div className="p-4 bg-[#0c0c0c] border border-gray-900 rounded-xl space-y-2">
                                  <div className="flex flex-wrap items-center gap-3 text-sm">
                                    {activeDetailNarrative.direction_bias != null && (
                                      <span style={{ color: getDirectionColor(activeDetailNarrative.direction_bias) }} className="font-bold uppercase">{activeDetailNarrative.direction_bias}</span>
                                    )}
                                    {activeDetailNarrative.expected_abs_move_pct != null && (
                                      <span>{t('stockDetail.expectedMove')}: <span style={{ color: getDirectionColor(activeDetailNarrative.direction_bias) }}>~{Number(activeDetailNarrative.expected_abs_move_pct).toFixed(1)}%</span></span>
                                    )}
                                    {(!activeDetailNarrative.direction_bias && activeDetailNarrative.expected_abs_move_pct == null) && (
                                      <span className="text-gray-500">{t('stockDetail.riskLabel')}: —</span>
                                    )}
                                  </div>
                                  {activeDetailNarrative.risk_drivers && activeDetailNarrative.risk_drivers.length > 0 && (
                                    <div className="pt-2 border-t border-gray-800">
                                      <span className="text-[9px] font-bold uppercase text-gray-500 tracking-wider">{t('stockDetail.riskDrivers')}: </span>
                                      <div className="flex flex-wrap gap-1.5 mt-1">
                                        {activeDetailNarrative.risk_drivers.map((d, i) => (
                                          <span key={i} className="px-2 py-0.5 rounded text-[10px] bg-gray-800 text-gray-400">{d}</span>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              </section>
                              {/* 2. Key story (summary + Linked to SEC) */}
                              <section>
                                <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('stockDetail.keyStory')}</h3>
                                <div className="p-5 bg-[#0c0c0c] border border-gray-900 rounded-xl">
                                  <p className="text-gray-400 text-sm leading-relaxed">{activeDetailNarrative.summary || t('stockDetail.noSummaryAvailable')}</p>
                                  {(activeDetailNarrative.is_filing_related || filingCitations.length > 0) && (
                                    <div className="mt-4 flex items-center gap-2 flex-wrap">
                                      <span className="px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider text-[#3b82f6] border border-[#3b82f6]/50">{t('stockDetail.linkedToSecFiling')}</span>
                                      {filingCitationsStatus === 'loaded' && filingCitations[0]?.filing_url && (
                                        <a href={filingCitations[0].filing_url} target="_blank" rel="noopener noreferrer" className="text-[#CCFF00] hover:underline text-[11px] font-medium">View full filing →</a>
                                      )}
                                    </div>
                                  )}
                                </div>
                              </section>
                              {/* 3. Supporting articles */}
                              <section>
                                <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('stockDetail.supportingArticles')}</h3>
                                <div className="space-y-8">
                                  {supportingArticlesStatus === 'loading' && (
                                    <p className="text-[11px] text-gray-500 italic">{t('stockDetail.loadingSupportingArticles')}</p>
                                  )}
                                  {supportingArticlesStatus === 'error' && (
                                    <p className="text-[11px] text-amber-500/90 italic">{t('stockDetail.supportArticlesError')}</p>
                                  )}
                                  {supportingArticlesStatus === 'loaded' && activeDetailNarrative.sourceEvents.length === 0 && (
                                    <p className="text-[11px] text-gray-500 italic">{t('stockDetail.noSupportingArticles')}</p>
                                  )}
                                  {activeDetailNarrative.sourceEvents.map((ev) => {
                                    const isExpanded = expandedSupportingId === ev.id;
                                    const hasSummary = !!ev.summary?.trim();
                                    return (
                                      <div key={ev.id} className="relative flex items-start group">
                                        <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight transition-colors group-hover:text-gray-400">
                                          {formatTimestamp(ev.timestamp)}
                                        </div>
                                        <div className="absolute left-[110px] top-2 -translate-x-1/2 w-2.5 h-2.5 rounded-full border border-black z-10 bg-gray-600 group-hover:bg-[#CCFF00] transition-all" />
                                        <div className="flex-1 pl-4 md:pl-12 pr-4">
                                          <div className="p-4 bg-[#0c0c0c] border border-gray-900 rounded-xl hover:border-gray-700 transition-all flex items-start gap-3">
                                            <button
                                              type="button"
                                              onClick={(e) => { e.stopPropagation(); setExpandedSupportingId((id) => (id === ev.id ? null : ev.id)); }}
                                              className="flex-shrink-0 p-0.5 rounded hover:bg-gray-800 text-gray-700 group-hover:text-[#CCFF00] transition-all"
                                              title={hasSummary ? (isExpanded ? t('stockDetail.hideSummary') : t('stockDetail.showSummary')) : t('stockDetail.noSummary')}
                                              disabled={!hasSummary}
                                            >
                                              <ChevronRight size={14} className={`mt-0.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                                            </button>
                                            {ev.url ? (
                                              <a href={ev.url} target="_blank" rel="noopener noreferrer" className="flex-1 min-w-0 cursor-pointer hover:underline underline-offset-2 decoration-[#CCFF00]/60">
                                                <div className="flex items-center justify-between gap-2 mb-1">
                                                  <span className="text-[8px] font-black text-gray-600 uppercase">{ev.source}</span>
                                                  {ev.relation_type ? <span className="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-wider bg-gray-800 text-gray-400 flex-shrink-0">{ev.relation_type.replace(/_/g, ' ')}</span> : null}
                                                </div>
                                                <span className="text-[11px] font-bold text-gray-400 hover:text-[#CCFF00] leading-tight block transition-colors">{ev.title}</span>
                                                {hasSummary && isExpanded && <p className="mt-3 text-[11px] text-gray-500 leading-relaxed border-t border-gray-800 pt-3">{ev.summary}</p>}
                                              </a>
                                            ) : (
                                              <div className="flex-1 min-w-0">
                                                <div className="flex items-center justify-between gap-2 mb-1">
                                                  <span className="text-[8px] font-black text-gray-600 uppercase">{ev.source}</span>
                                                  {ev.relation_type ? <span className="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-wider bg-gray-800 text-gray-400 flex-shrink-0">{ev.relation_type.replace(/_/g, ' ')}</span> : null}
                                                </div>
                                                <h4 className="text-[11px] font-bold text-gray-400 group-hover:text-white leading-tight">{ev.title}</h4>
                                                {hasSummary && isExpanded && <p className="mt-3 text-[11px] text-gray-500 leading-relaxed border-t border-gray-800 pt-3">{ev.summary}</p>}
                                              </div>
                                            )}
                                          </div>
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              </section>
                              {/* 4. SEC filing excerpt(s) - when linked */}
                              {(activeDetailNarrative.is_filing_related || filingCitations.length > 0) && (
                                <section>
                                  <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">{t('stockDetail.secFilingExcerpts')}</h3>
                                  <div className="space-y-8">
                                    {filingCitationsStatus === 'loading' && (
                                      <p className="text-[11px] text-gray-500 italic">{t('stockDetail.loadingFilingExcerpts')}</p>
                                    )}
                                    {filingCitationsStatus === 'error' && (
                                      <p className="text-[11px] text-amber-500/90 italic">{t('stockDetail.noFilingExcerpts')}</p>
                                    )}
                                    {filingCitationsStatus === 'loaded' && filingCitations.length === 0 && (
                                      <p className="text-[11px] text-gray-500 italic">{t('stockDetail.noSecExcerptForStory')}</p>
                                    )}
                                    {filingCitationsStatus === 'loaded' && filingCitations.map((cit, idx) => {
                                      const isExpanded = expandedFilingCitationId === cit.chunk_id;
                                      const hasText = !!cit.text?.trim();
                                      const hasSummary = !!cit.summary?.trim();
                                      const title = cit.filing_title ?? (cit.form_type ? `${cit.form_type} excerpt` : `Excerpt ${idx + 1}`);
                                      const formatted = formattedChunkByCitationId[cit.chunk_id];
                                      const formatting = formattedChunkLoadingById[cit.chunk_id];
                                      const formatError = formattedChunkErrorById[cit.chunk_id];
                                      const displayText = formatted ?? cit.text;
                                      const looksLikeMarkdownTable = (s: string) => /\|.+\|/.test(s) && (s.includes('---') || s.split('\n').filter(l => l.includes('|')).length >= 2);
                                      const renderTable = (raw: string) => {
                                        const lines = raw.trim().split('\n').filter(Boolean);
                                        const sep = lines.some(l => l.includes('|')) ? '|' : '\t';
                                        const parsed = lines.map(l => l.split(sep).map(c => c.trim()));
                                        const isSeparatorRow = (cells: string[]) => cells.length > 0 && cells.every(c => /^[\s\-]*$/.test(c));
                                        const dataRows = parsed.filter(row => row.length > 0 && !isSeparatorRow(row));
                                        if (dataRows.length === 0) return <p className="mt-3 text-[11px] text-gray-500 whitespace-pre-wrap border-t border-gray-800 pt-3">{raw}</p>;
                                        const numCols = Math.max(...dataRows.map(r => r.length));
                                        const padRow = (row: string[]) => [...row, ...Array(Math.max(0, numCols - row.length)).fill('')];
                                        const header = dataRows[0];
                                        const body = dataRows.slice(1);
                                        return (
                                          <div className="mt-3 overflow-x-auto border-t border-gray-800 pt-3">
                                            <table className="w-full min-w-[200px] text-[11px] text-gray-500 border-collapse">
                                              <thead>
                                                <tr>
                                                  {padRow(header).map((cell, j) => (
                                                    <th key={j} className="px-2 py-1.5 border border-gray-700 bg-gray-900/50 text-gray-400 text-left font-semibold">{cell || '\u00a0'}</th>
                                                  ))}
                                                </tr>
                                              </thead>
                                              <tbody>
                                                {body.map((row, i) => (
                                                  <tr key={i}>
                                                    {padRow(row).map((cell, j) => (
                                                      <td key={j} className="px-2 py-1 border border-gray-800 align-top">{cell || '\u00a0'}</td>
                                                    ))}
                                                  </tr>
                                                ))}
                                              </tbody>
                                            </table>
                                          </div>
                                        );
                                      };
                                      const renderFormattedChunk = (text: string) =>
                                        looksLikeMarkdownTable(text) ? renderTable(text) : (
                                          <p className="text-[11px] text-gray-500 leading-relaxed whitespace-pre-wrap">{text}</p>
                                        );
                                      return (
                                        <div key={cit.chunk_id} className="relative flex items-start group">
                                          <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight transition-colors group-hover:text-gray-400">
                                            {cit.filed_date ?? '—'}
                                          </div>
                                          <div className="absolute left-[110px] top-2 -translate-x-1/2 w-2.5 h-2.5 rounded-full border border-black z-10 bg-gray-600 group-hover:bg-[#CCFF00] transition-all" />
                                          <div className="flex-1 pl-4 md:pl-12 pr-4">
                                            <div className="p-4 bg-[#0c0c0c] border border-gray-900 rounded-xl hover:border-gray-700 transition-all flex items-start gap-3">
                                              <button
                                                type="button"
                                                onClick={() => setExpandedFilingCitationId((id) => (id === cit.chunk_id ? null : cit.chunk_id))}
                                                className="flex-shrink-0 p-0.5 rounded hover:bg-gray-800 text-gray-700 group-hover:text-[#CCFF00] transition-all"
                                                title={hasText ? (isExpanded ? t('stockDetail.hideFullExcerpt') : t('stockDetail.showFullExcerpt')) : hasSummary ? t('stockDetail.summaryOnly') : t('stockDetail.noText')}
                                                disabled={!hasText && !hasSummary}
                                              >
                                                <ChevronRight size={14} className={`mt-0.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                                              </button>
                                              <div className="flex-1 min-w-0">
                                                <div className="flex items-center justify-between gap-2 mb-1">
                                                  <span className="text-[8px] font-black text-gray-600 uppercase">{title}</span>
                                                  {cit.form_type ? <span className="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-wider bg-gray-800 text-gray-400 flex-shrink-0">{cit.form_type}</span> : null}
                                                </div>
                                                {hasSummary && <p className="text-[11px] text-gray-300 leading-relaxed">{cit.summary}</p>}
                                                {hasText && isExpanded && (
                                                  <div className={hasSummary ? 'mt-3 border-t border-gray-800 pt-3' : ''}>
                                                    {formatting && <p className="text-[11px] text-gray-500 italic">Formatting for readability…</p>}
                                                    {!formatting && (formatted ?? formatError) && (
                                                      <>
                                                        {formatError && <p className="text-[11px] text-amber-500/90 italic mb-2">Formatting failed; showing raw excerpt.</p>}
                                                        {renderFormattedChunk(displayText)}
                                                      </>
                                                    )}
                                                    {!formatting && !formatted && !formatError && renderFormattedChunk(cit.text)}
                                                  </div>
                                                )}
                                                {!hasSummary && hasText && !isExpanded && <p className="mt-1 text-[11px] text-gray-500 italic">Expand to view {cit.is_table ? 'table' : 'excerpt'}</p>}
                                                {cit.filing_url && (hasSummary || hasText) && (
                                                  <a href={cit.filing_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="mt-2 inline-block text-[#CCFF00] hover:underline text-[11px] font-medium">View full filing →</a>
                                                )}
                                              </div>
                                            </div>
                                          </div>
                                        </div>
                                      );
                                    })}
                                  </div>
                                </section>
                              )}
                            </>
                          ) : (
                          <>
                          {/* 1. Supporting content: filing citations (SEC Insight) or articles (short/long) */}
                          <section>
                            <h3 className="text-[9px] font-black uppercase text-gray-600 tracking-[0.2em] mb-3">
                              {activeDetailNarrative.storyType === 'filing' ? t('stockDetail.secFilingExcerpts') : activeDetailNarrative.storylineId ? t('stockDetail.supportingArticles') : t('stockDetail.constituentEvidence')}
                            </h3>
                            <div className="space-y-8">
                              {activeDetailNarrative.storyType === 'filing' ? (
                                <>
                                  {filingCitationsStatus === 'loading' && (
                                    <p className="text-[11px] text-gray-500 italic">Loading filing excerpts…</p>
                                  )}
                                  {filingCitationsStatus === 'error' && (
                                    <p className="text-[11px] text-amber-500/90 italic">Unable to load filing excerpts. Check the backend or try again.</p>
                                  )}
                                  {filingCitationsStatus === 'loaded' && filingCitations.length === 0 && (
                                    <p className="text-[11px] text-gray-500 italic">{t('stockDetail.noFilingExcerptsForInsight')}</p>
                                  )}
                                  {filingCitationsStatus === 'loaded' && filingCitations.map((cit, idx) => {
                                    const isExpanded = expandedFilingCitationId === cit.chunk_id;
                                    const hasText = !!cit.text?.trim();
                                    const hasSummary = !!cit.summary?.trim();
                                    const title = cit.filing_title ?? (cit.form_type ? `${cit.form_type} excerpt` : `Excerpt ${idx + 1}`);
                                    const formatted = formattedChunkByCitationId[cit.chunk_id];
                                    const formatting = formattedChunkLoadingById[cit.chunk_id];
                                    const formatError = formattedChunkErrorById[cit.chunk_id];
                                    const displayText = formatted ?? cit.text;
                                    const looksLikeMarkdownTable = (s: string) => /\|.+\|/.test(s) && (s.includes('---') || s.split('\n').filter(l => l.includes('|')).length >= 2);
                                    const renderTable = (raw: string) => {
                                      const lines = raw.trim().split('\n').filter(Boolean);
                                      const sep = lines.some(l => l.includes('|')) ? '|' : '\t';
                                      const parsed = lines.map(l => l.split(sep).map(c => c.trim()));
                                      const isSeparatorRow = (cells: string[]) => cells.length > 0 && cells.every(c => /^[\s\-]*$/.test(c));
                                      const dataRows = parsed.filter(row => row.length > 0 && !isSeparatorRow(row));
                                      if (dataRows.length === 0) return <p className="mt-3 text-[11px] text-gray-500 whitespace-pre-wrap border-t border-gray-800 pt-3">{raw}</p>;
                                      const numCols = Math.max(...dataRows.map(r => r.length));
                                      const padRow = (row: string[]) => [...row, ...Array(Math.max(0, numCols - row.length)).fill('')];
                                      const header = dataRows[0];
                                      const body = dataRows.slice(1);
                                      return (
                                        <div className="mt-3 overflow-x-auto border-t border-gray-800 pt-3">
                                          <table className="w-full min-w-[200px] text-[11px] text-gray-500 border-collapse">
                                            <thead>
                                              <tr>
                                                {padRow(header).map((cell, j) => (
                                                  <th key={j} className="px-2 py-1.5 border border-gray-700 bg-gray-900/50 text-gray-400 text-left font-semibold">{cell || '\u00a0'}</th>
                                                ))}
                                              </tr>
                                            </thead>
                                            <tbody>
                                              {body.map((row, i) => (
                                                <tr key={i}>
                                                  {padRow(row).map((cell, j) => (
                                                    <td key={j} className="px-2 py-1 border border-gray-800 align-top">{cell || '\u00a0'}</td>
                                                  ))}
                                                </tr>
                                              ))}
                                            </tbody>
                                          </table>
                                        </div>
                                      );
                                    };
                                    const renderFormattedChunk = (text: string) =>
                                      looksLikeMarkdownTable(text) ? renderTable(text) : (
                                        <p className="text-[11px] text-gray-500 leading-relaxed whitespace-pre-wrap">{text}</p>
                                      );
                                    return (
                                      <div key={cit.chunk_id} className="relative flex items-start group">
                                        <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight transition-colors group-hover:text-gray-400">
                                          {cit.filed_date ?? '—'}
                                        </div>
                                        <div className="absolute left-[110px] top-2 -translate-x-1/2 w-2.5 h-2.5 rounded-full border border-black z-10 bg-gray-600 group-hover:bg-[#CCFF00] transition-all" />
                                        <div className="flex-1 pl-4 md:pl-12 pr-4">
                                          <div className="p-4 bg-[#0c0c0c] border border-gray-900 rounded-xl hover:border-gray-700 transition-all flex items-start gap-3">
                                            <button
                                              type="button"
                                              onClick={() => setExpandedFilingCitationId((id) => (id === cit.chunk_id ? null : cit.chunk_id))}
                                              className="flex-shrink-0 p-0.5 rounded hover:bg-gray-800 text-gray-700 group-hover:text-[#CCFF00] transition-all"
                                              title={hasText ? (isExpanded ? t('stockDetail.hideFullExcerpt') : t('stockDetail.showFullExcerpt')) : hasSummary ? t('stockDetail.summaryOnly') : t('stockDetail.noText')}
                                              disabled={!hasText && !hasSummary}
                                            >
                                              <ChevronRight size={14} className={`mt-0.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                                            </button>
                                            <div className="flex-1 min-w-0">
                                              <div className="flex items-center justify-between gap-2 mb-1">
                                                <span className="text-[8px] font-black text-gray-600 uppercase">{title}</span>
                                                {cit.form_type ? (
                                                  <span className="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-wider bg-gray-800 text-gray-400 flex-shrink-0">
                                                    {cit.form_type}
                                                  </span>
                                                ) : null}
                                              </div>
                                              {hasSummary && (
                                                <p className="text-[11px] text-gray-300 leading-relaxed">
                                                  {cit.summary}
                                                </p>
                                              )}
                                              {hasText && isExpanded && (
                                                <div className={hasSummary ? 'mt-3 border-t border-gray-800 pt-3' : ''}>
                                                {formatting && (
                                                  <p className="text-[11px] text-gray-500 italic">Formatting for readability…</p>
                                                )}
                                                {!formatting && (formatted ?? formatError) && (
                                                  <>
                                                    {formatError && (
                                                      <p className="text-[11px] text-amber-500/90 italic mb-2">Formatting failed; showing raw excerpt.</p>
                                                    )}
                                                    {renderFormattedChunk(displayText)}
                                                  </>
                                                )}
                                                {!formatting && !formatted && !formatError && (
                                                  renderFormattedChunk(cit.text)
                                                )}
                                              </div>
                                              )}
                                              {!hasSummary && hasText && !isExpanded && (
                                                <p className="mt-1 text-[11px] text-gray-500 italic">Expand to view {cit.is_table ? 'table' : 'excerpt'}</p>
                                              )}
                                              {cit.filing_url && (hasSummary || hasText) && (
                                                <a
                                                  href={cit.filing_url}
                                                  target="_blank"
                                                  rel="noopener noreferrer"
                                                  onClick={(e) => e.stopPropagation()}
                                                  className="mt-2 inline-block text-[#CCFF00] hover:underline text-[11px] font-medium"
                                                >
                                                  View full filing →
                                                </a>
                                              )}
                                            </div>
                                          </div>
                                        </div>
                                      </div>
                                    );
                                  })}
                                </>
                              ) : (
                                <>
                                  {activeDetailNarrative.storylineId != null && activeDetailNarrative.sourceEvents.length === 0 && (
                                    <>
                                      {supportingArticlesStatus === 'loading' && (
                                        <p className="text-[11px] text-gray-500 italic">Loading supporting articles…</p>
                                      )}
                                      {supportingArticlesStatus === 'error' && (
                                        <p className="text-[11px] text-amber-500/90 italic">Unable to load articles. Check the backend or try again.</p>
                                      )}
                                      {supportingArticlesStatus === 'loaded' && (
                                        <p className="text-[11px] text-gray-500 italic">No supporting articles for this storyline.</p>
                                      )}
                                    </>
                                  )}
                                  {activeDetailNarrative.sourceEvents.map((ev) => {
                                    const isExpanded = expandedSupportingId === ev.id;
                                    const hasSummary = !!ev.summary?.trim();
                                    return (
                                      <div key={ev.id} className="relative flex items-start group">
                                        <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight transition-colors group-hover:text-gray-400">
                                          {formatTimestamp(ev.timestamp)}
                                        </div>
                                        <div className="absolute left-[110px] top-2 -translate-x-1/2 w-2.5 h-2.5 rounded-full border border-black z-10 bg-gray-600 group-hover:bg-[#CCFF00] transition-all" />
                                        <div className="flex-1 pl-4 md:pl-12 pr-4">
                                          <div className="p-4 bg-[#0c0c0c] border border-gray-900 rounded-xl hover:border-gray-700 transition-all flex items-start gap-3">
                                            <button
                                              type="button"
                                              onClick={(e) => { e.stopPropagation(); setExpandedSupportingId((id) => (id === ev.id ? null : ev.id)); }}
                                              className="flex-shrink-0 p-0.5 rounded hover:bg-gray-800 text-gray-700 group-hover:text-[#CCFF00] transition-all"
                                              title={hasSummary ? (isExpanded ? t('stockDetail.hideSummary') : t('stockDetail.showSummary')) : t('stockDetail.noSummary')}
                                              disabled={!hasSummary}
                                            >
                                              <ChevronRight size={14} className={`mt-0.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                                            </button>
                                            {ev.url ? (
                                              <a
                                                href={ev.url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="flex-1 min-w-0 cursor-pointer hover:underline underline-offset-2 decoration-[#CCFF00]/60"
                                              >
                                                <div className="flex items-center justify-between gap-2 mb-1">
                                                  <span className="text-[8px] font-black text-gray-600 uppercase">{ev.source}</span>
                                                  {ev.relation_type ? (
                                                    <span className="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-wider bg-gray-800 text-gray-400 flex-shrink-0">
                                                      {ev.relation_type.replace(/_/g, ' ')}
                                                    </span>
                                                  ) : null}
                                                </div>
                                                <span className="text-[11px] font-bold text-gray-400 hover:text-[#CCFF00] leading-tight block transition-colors">
                                                  {ev.title}
                                                </span>
                                                {hasSummary && isExpanded && (
                                                  <p className="mt-3 text-[11px] text-gray-500 leading-relaxed border-t border-gray-800 pt-3">
                                                    {ev.summary}
                                                  </p>
                                                )}
                                              </a>
                                            ) : (
                                              <div className="flex-1 min-w-0">
                                                <div className="flex items-center justify-between gap-2 mb-1">
                                                  <span className="text-[8px] font-black text-gray-600 uppercase">{ev.source}</span>
                                                  {ev.relation_type ? (
                                                    <span className="px-2 py-0.5 rounded text-[8px] font-black uppercase tracking-wider bg-gray-800 text-gray-400 flex-shrink-0">
                                                      {ev.relation_type.replace(/_/g, ' ')}
                                                    </span>
                                                  ) : null}
                                                </div>
                                                <h4 className="text-[11px] font-bold text-gray-400 group-hover:text-white leading-tight">{ev.title}</h4>
                                                {hasSummary && isExpanded && (
                                                  <p className="mt-3 text-[11px] text-gray-500 leading-relaxed border-t border-gray-800 pt-3">
                                                    {ev.summary}
                                                  </p>
                                                )}
                                              </div>
                                            )}
                                          </div>
                                        </div>
                                      </div>
                                    );
                                  })}
                                </>
                              )}
                            </div>
                          </section>
                          {/* 2. Narrative Synthesis */}
                          <section>
                            <h3 className="text-[9px] font-black uppercase text-[#CCFF00] tracking-[0.2em] mb-3 flex items-center gap-2">
                              <Sparkles size={10} /> AI Narrative Synthesis
                            </h3>
                            <div className="bg-[#CCFF00]/5 p-5 rounded-xl border border-[#CCFF00]/10">
                              <p className="text-sm text-gray-200 leading-relaxed italic">
                                {activeDetailNarrative.summary}
                              </p>
                            </div>
                          </section>
                          </>
                          )}
                        </div>
                      </div>
                    )}
                    {longStoryTimelineOpen && (
                      <LongStoryTimeline
                        loading={longStoryTimelineLoading}
                        title={longStoryTimelineTitle}
                        summary={longStoryTimelineSummary}
                        theme={longStoryTimelineTheme}
                        timeline={longStoryTimeline}
                        onClose={handleCloseStorylineDetail}
                        formatTimestamp={formatTimestamp}
                      />
                    )}
                  </div>
                </>
              ) : (
              <div className="contents">
              <div className="relative min-h-full pb-32 animate-in fade-in duration-300">
                <NewsFilterPanel
                  selectedTimeframe={selectedTimeframe}
                  customRange={customRange}
                  onTimeframeChange={setSelectedTimeframe}
                  onCustomRangeChange={setCustomRange}
                />
                {loadingStorylines && selectedCategories.includes('Stock') && (
                  <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-6">Loading storylines…</div>
                )}
                {loadingMacroNews && selectedCategories.includes('Macro') && (
                  <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-6">Loading macro news…</div>
                )}
                {selectedCategories.includes('Stock') && (
                  <div className="flex items-center gap-2 mb-6">
                    <button
                      onClick={() => setStorylineSubtab('overnightImpact')}
                      className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold transition-colors ${
                        storylineSubtab === 'overnightImpact' ? 'bg-[#CCFF00] text-black' : 'bg-[#121212] text-gray-400 hover:text-white border border-gray-800'
                      }`}
                    >
                      {t('stockDetail.overnightImpact')}
                    </button>
                    <button
                      onClick={() => setStorylineSubtab('longStory')}
                      className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold transition-colors ${
                        storylineSubtab === 'longStory' ? 'bg-[#CCFF00] text-black' : 'bg-[#121212] text-gray-400 hover:text-white border border-gray-800'
                      }`}
                    >
                      Long Story
                    </button>
                  </div>
                )}
                <div className="relative">
                  {(selectedCategories.includes('Stock')
                    ? subtabItems.length
                    : isCausalMode
                      ? narrativeTimeline.length
                      : filteredNews.length) > 0 && (
                    <div className="absolute left-[110px] top-0 bottom-0 w-[1px] bg-gray-900 hidden md:block pointer-events-none" aria-hidden />
                  )}
                  <div className="space-y-16">
                  {selectedCategories.includes('Stock') ? (
                    subtabItems.length > 0 ? (
                      subtabItems.map((narrative) => {
                        const impactColor = getSentimentColor(narrative.sentiment);
                        const isLong = narrative.storyType === 'long';
                        const isFiling = narrative.storyType === 'filing';
                        const isOvernight = narrative.storyType === 'overnight';
                        const directionColor = getDirectionColor(narrative.direction_bias);
                        const hasAnyRisk = isOvernight && (narrative.expected_abs_move_pct != null || narrative.direction_bias != null);
                        return (
                          <div key={narrative.id} className="relative flex items-start group">
                            <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight transition-colors group-hover:text-gray-400">
                              {formatTimestamp(narrative.timestamp)}
                            </div>
                            <div
                              className="absolute left-[110px] top-2 -translate-x-1/2 w-3.5 h-3.5 rounded-full border-2 border-black z-10 transition-all duration-300 group-hover:scale-125 shadow-[0_0_10px_rgba(204,255,0,0.4)] flex items-center justify-center"
                              style={{ backgroundColor: impactColor }}
                            >
                              <Sparkles size={8} className="text-black" />
                            </div>
                            <div
                              onClick={() => isLong ? handleOpenLongStoryTimeline(narrative.id, narrative.title) : handleOpenNarrativeDetail(narrative)}
                              className="flex-1 pl-4 md:pl-12 pr-4 bg-[#0a0a0a]/50 p-6 rounded-xl border transition-all cursor-pointer hover:border-gray-700"
                              style={{ borderLeft: `2px solid ${impactColor}`, borderColor: 'rgba(31, 41, 55, 0.5)' }}
                            >
                              <div className="flex items-center gap-3 mb-2 flex-wrap">
                                <span
                                  className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest"
                                  style={{ backgroundColor: isFiling ? 'rgba(59, 130, 246, 0.15)' : (isOvernight || isLong) ? 'rgba(204, 255, 0, 0.15)' : `${impactColor}22`, color: isFiling ? '#3b82f6' : (isOvernight || isLong) ? '#CCFF00' : impactColor }}
                                >
                                  {isFiling ? t('stockDetail.secInsight') : isLong ? t('stockDetail.longStory') : isOvernight ? (narrative.session_display_label === 'Intraday' ? t('stockDetail.intraday') : narrative.session_display_label === 'Mixed' ? t('stockDetail.mixed') : t('stockDetail.overnight')) : t('stockDetail.stockStory')}
                                </span>
                                {isOvernight && narrative.is_filing_related && (
                                  <span className="px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider text-[#3b82f6] border border-[#3b82f6]/50">{t('stockDetail.linkedToSecFiling')}</span>
                                )}
                                {isOvernight && (
                                  <span className="text-[9px] font-bold text-gray-500 uppercase tracking-wider">
                                    {hasAnyRisk ? (
                                      <>
                                        {narrative.direction_bias != null && <span style={{ color: directionColor }}>{narrative.direction_bias}</span>}
                                        {narrative.expected_abs_move_pct != null && <span style={{ color: directionColor }}> · ~{Number(narrative.expected_abs_move_pct).toFixed(1)}%</span>}
                                      </>
                                    ) : (
                                      <span>{t('stockDetail.riskLabel')}: —</span>
                                    )}
                                  </span>
                                )}
                                {(narrative.storyType === 'short' || narrative.storyType === 'long') && insightMap[narrative.id] && (
                                  <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); handleOpenNarrativeDetail(insightMap[narrative.id]); }}
                                    className="flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest border border-gray-700 text-gray-400 hover:border-[#3b82f6] hover:text-[#3b82f6] transition-colors"
                                    title="View filing insight"
                                  >
                                    <Sparkles size={10} /> Insight
                                  </button>
                                )}
                              </div>
                              <h4 className={`text-lg font-bold mb-3 leading-snug transition-colors ${(activeDetailNarrative || (longStoryTimelineOpen && activeLongStoryId === narrative.id)) && (activeDetailNarrative?.id === narrative.id || (longStoryTimelineOpen && activeLongStoryId === narrative.id)) ? 'text-[#CCFF00]' : 'text-gray-100 group-hover:text-[#CCFF00]'}`}>{narrative.title}</h4>
                              <p className="text-sm text-gray-400 leading-relaxed font-medium italic line-clamp-2">
                                "{narrative.summary}"
                              </p>
                              <div className="mt-5 flex items-center justify-between">
                                <button className="text-[9px] font-black text-gray-700 uppercase tracking-[0.2em] group-hover:text-[#CCFF00] transition-colors flex items-center gap-1">{t('stockDetail.viewSupportingArticles')} <span className="text-lg leading-none mb-0.5">→</span></button>
                              </div>
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <div className="py-20 text-center space-y-2">
                        <p className="text-gray-500 text-sm font-medium">
                          {storylineSubtab === 'longStory' && longStoriesFetchError
                            ? t('stockDetail.longStoriesLoadError')
                            : storylineSubtab === 'overnightImpact'
                              ? t('stockDetail.noOvernightStories')
                              : storylineSubtab === 'longStory'
                                ? t('stockDetail.noLongStories')
                                : t('stockDetail.noSecInsights')}
                        </p>
                        {storylineSubtab === 'longStory' && !longStoriesFetchError && (
                          <p className="text-gray-600 text-xs max-w-sm mx-auto">{t('stockDetail.longStoriesEmptyHint')}</p>
                        )}
                      </div>
                    )
                  ) : isCausalMode ? (
                    narrativeTimeline.map((narrative) => {
                      const impactColor = getSentimentColor(narrative.sentiment);
                      return (
                        <div key={narrative.id} className="relative flex items-start group">
                          <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight transition-colors group-hover:text-gray-400">
                            {formatTimestamp(narrative.timestamp)}
                          </div>
                          <div 
                            className="absolute left-[110px] top-2 -translate-x-1/2 w-3.5 h-3.5 rounded-full border-2 border-black z-10 transition-all duration-300 group-hover:scale-125 shadow-[0_0_10px_rgba(204,255,0,0.4)] flex items-center justify-center"
                            style={{ backgroundColor: impactColor }}
                          >
                            <Sparkles size={8} className="text-black" />
                          </div>
                          <div 
                            onClick={() => handleOpenNarrativeDetail(narrative)}
                            className="flex-1 pl-4 md:pl-12 pr-4 bg-[#0a0a0a]/50 p-6 rounded-xl border transition-all cursor-pointer hover:border-gray-700"
                            style={{ borderLeft: `2px solid ${impactColor}`, borderColor: 'rgba(31, 41, 55, 0.5)' }}
                          >
                            <div className="flex items-center gap-3 mb-2">
                               <span 
                                 className="px-2 py-0.5 rounded text-[9px] font-black uppercase tracking-widest"
                                 style={{ backgroundColor: `${impactColor}22`, color: impactColor }}
                               >
                                 {t('stockDetail.syntheticInsight')}
                               </span>
                               <span className="text-[9px] font-bold text-gray-600 uppercase tracking-widest">{t('stockDetail.aggregatingEvents', { count: narrative.newsCount })}</span>
                            </div>
                            <h4 className="text-lg font-bold mb-3 text-gray-100 leading-snug group-hover:text-[#CCFF00] transition-colors">{narrative.title}</h4>
                            <p className="text-sm text-gray-400 leading-relaxed font-medium italic line-clamp-2">
                              "{narrative.summary}"
                            </p>
                            <div className="mt-5 flex items-center justify-between">
                              <button className="text-[9px] font-black text-gray-700 uppercase tracking-[0.2em] group-hover:text-[#CCFF00] transition-colors flex items-center gap-1">{t('stockDetail.deconstructEvidence')} <span className="text-lg leading-none mb-0.5">→</span></button>
                              <div className="flex items-center gap-2">
                                <span className="text-[10px] font-bold text-gray-600 uppercase tracking-widest">Historical Impact:</span>
                                <span className="text-[10px] font-black uppercase tracking-widest" style={{ color: impactColor }}>{narrative.sentiment}</span>
                              </div>
                            </div>
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    filteredNews.map((news) => (
                      <div key={news.id} className="relative flex items-start group">
                        <div className="w-[110px] flex-shrink-0 text-[9px] font-bold text-gray-600 uppercase pt-1 tracking-tighter text-right pr-8 leading-tight transition-colors group-hover:text-gray-400">
                          {formatTimestamp(news.timestamp)}
                        </div>
                        <div className="absolute left-[110px] top-2 -translate-x-1/2 w-2.5 h-2.5 rounded-full border border-black z-10 transition-all duration-300 group-hover:scale-150 ring-4 ring-black" style={{ backgroundColor: getSentimentColor(news.sentiment) }}></div>
                        <div 
                          onClick={() => handleOpenNewsDetail(news)}
                          className="flex-1 pl-4 md:pl-12 pr-4 cursor-pointer"
                        >
                          <div className="flex items-center gap-3 mb-2">
                            <span className="px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider" style={{ backgroundColor: `${CATEGORY_COLORS[news.category]}22`, color: CATEGORY_COLORS[news.category] }}>{news.category}</span>
                            <span className="text-[10px] font-semibold text-gray-600 tracking-wide uppercase">{news.source}</span>
                          </div>
                          <h4 className="text-base font-bold mb-3 group-hover:text-[#CCFF00] transition-colors leading-snug text-gray-100">{news.title}</h4>
                          <p className="text-[13px] text-gray-500 leading-relaxed font-medium">{news.summary}</p>
                          <div className="mt-5 flex items-center gap-4">
                            <button className="text-[9px] font-black text-gray-700 uppercase tracking-[0.2em] hover:text-[#CCFF00] transition-colors flex items-center gap-1">{t('stockDetail.exploreNarrative')} <span className="text-lg leading-none mb-0.5">→</span></button>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                  </div>
                </div>
              </div>
              </div>
            )
          ) : (
              <div className="animate-in fade-in duration-500">
                <TradingViewChart stock={stock} timeframe={selectedTimeframe} />
              </div>
            )}

            {activeTab === 'Storyline' && !selectedCategories.includes('Stock') && (isCausalMode ? narrativeTimeline.length : filteredNews.length) === 0 && !loadingStorylines && (
              <div className="py-20 text-center">
                <div className="w-12 h-12 rounded-full border border-gray-900 flex items-center justify-center mx-auto mb-4"><div className="w-1 h-1 rounded-full bg-gray-700"></div></div>
                <p className="text-gray-500 text-sm font-medium">
                  {selectedCategories.includes('Stock') && storylinesFetchError
                    ? 'Could not load storylines. Check that the API URL (VITE_API_URL) is set and CORS allows this site.'
                    : selectedCategories.includes('Stock') && stockStorylines.length === 0
                      ? 'No storylines for this stock yet.'
                      : 'No results match your criteria.'}
                </p>
                <button onClick={() => { setSelectedCategories(CATEGORIES); setSelectedTimeframe('2D'); setCustomRange({ start: '', end: '' }); setIsCausalMode(false); }} className="mt-4 text-[10px] font-bold text-[#CCFF00] uppercase tracking-widest hover:underline">Reset filters</button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default StockDetail;
