import React, { useState, useEffect, useRef } from 'react';
import { Stock, ViewType } from '../types';
import { useLocale } from '../i18n';
import { getPredictionStyle } from '../constants';
import StockCard from './StockCard';
import StockDetail from './StockDetail';
import MacroView from './MacroView';
import LanguageSwitcher from './LanguageSwitcher';
import { Search, ChevronDown, Plus, LogOut, ArrowLeft, MessageSquare, Send, Menu, X, ExternalLink, Trash2 } from 'lucide-react';

const API_BASE = (import.meta as unknown as { env?: { VITE_API_URL?: string } }).env?.VITE_API_URL ?? 'http://localhost:8000';

/** Compute overnight window: most recent business day (weekday) 4pm America/New_York to now. Returns ISO8601 UTC strings. */
function getOvernightWindowFallback(): { start: string; end: string } {
  const now = new Date();
  const nyFmt = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit' });
  const parts = nyFmt.formatToParts(now);
  const get = (t: string) => parseInt(parts.find((p) => p.type === t)?.value ?? '0', 10);
  const y = get('year');
  const m = get('month') - 1;
  const d = get('day');
  const nyHour = get('hour');
  // Reference date in NY: today if >= 4pm ET, else yesterday
  let refY = y;
  let refM = m;
  let refD = nyHour >= 16 ? d : d - 1;
  if (refD < 1) {
    refM -= 1;
    if (refM < 0) {
      refM = 11;
      refY -= 1;
    }
    refD = new Date(Date.UTC(refY, refM + 1, 0)).getUTCDate();
  }
  // Walk back to most recent weekday (no holiday list in frontend)
  const isWeekend = (yr: number, mo: number, day: number) => {
    const w = new Date(Date.UTC(yr, mo, day)).getUTCDay();
    return w === 0 || w === 6;
  };
  while (isWeekend(refY, refM, refD)) {
    refD -= 1;
    if (refD < 1) {
      refM -= 1;
      if (refM < 0) {
        refM = 11;
        refY -= 1;
      }
      refD = new Date(Date.UTC(refY, refM + 1, 0)).getUTCDate();
    }
  }
  // 4pm ET: EST = 21:00 UTC, EDT ≈ 20:00 UTC (March–October)
  const hr4pmUtc = refM >= 2 && refM <= 9 ? 20 : 21;
  const start = new Date(Date.UTC(refY, refM, refD, hr4pmUtc, 0, 0, 0));
  return { start: start.toISOString(), end: now.toISOString() };
}

interface DashboardProps {
  username: string;
  onLogout: () => void;
}

interface StockInfo {
  ticker: string;
  name: string;
  exchange: string;
}

// Removed hardcoded STOCK_DATABASE - now fetched from API

// Default portfolio stocks
const INITIAL_PORTFOLIO: Stock[] = [
  { symbol: 'AAPL', name: 'Apple Inc.', price: 0, change: 0, changePercent: 0 },
  { symbol: 'MSFT', name: 'Microsoft Corp', price: 0, change: 0, changePercent: 0 },
  { symbol: 'AMZN', name: 'Amazon.com Inc.', price: 0, change: 0, changePercent: 0 },
  { symbol: 'GOOGL', name: 'Alphabet Inc.', price: 0, change: 0, changePercent: 0 },
  { symbol: 'META', name: 'Meta Platforms, Inc.', price: 0, change: 0, changePercent: 0 },
  { symbol: 'NVDA', name: 'NVIDIA Corp', price: 0, change: 0, changePercent: 0 },
  { symbol: 'TSLA', name: 'Tesla, Inc.', price: 0, change: 0, changePercent: 0 },
];

const INITIAL_WATCHLIST: Stock[] = [
  { symbol: 'COST', name: 'Costco Wholesale Corp', price: 0, change: 0, changePercent: 0 },
  { symbol: 'NFLX', name: 'Netflix, Inc.', price: 0, change: 0, changePercent: 0 },
  { symbol: 'ASML', name: 'ASML Holding NV', price: 0, change: 0, changePercent: 0 },
  { symbol: 'ADBE', name: 'Adobe Inc.', price: 0, change: 0, changePercent: 0 },
  { symbol: 'CSCO', name: 'Cisco Systems, Inc.', price: 0, change: 0, changePercent: 0 },
  { symbol: 'AMD', name: 'Advanced Micro Devices, Inc.', price: 0, change: 0, changePercent: 0 },
  { symbol: 'QCOM', name: 'QUALCOMM Incorporated', price: 0, change: 0, changePercent: 0 },
];

const CUSTOM_STORY_MAX_CHARS = 200;

// SessionStorage keys
const PORTFOLIO_STORAGE_KEY = 'morningedge_portfolio';
const WATCHLIST_STORAGE_KEY = 'morningedge_watchlist';

// Helper functions for sessionStorage
const loadFromSessionStorage = (key: string, defaultValue: Stock[]): Stock[] => {
  if (typeof window === 'undefined') return defaultValue;
  try {
    const stored = sessionStorage.getItem(key);
    if (stored) {
      const parsed = JSON.parse(stored) as Array<{ symbol: string; name: string }>;
      // Convert to Stock format with zero prices (prices will be fetched from API)
      return parsed.map(s => ({
        symbol: s.symbol,
        name: s.name,
        price: 0,
        change: 0,
        changePercent: 0,
      }));
    }
  } catch (err) {
    console.error(`Error loading ${key} from sessionStorage:`, err);
  }
  return defaultValue;
};

const saveToSessionStorage = (key: string, stocks: Stock[]): void => {
  if (typeof window === 'undefined') return;
  try {
    // Only store symbol and name, not price data
    const dataToStore = stocks.map(s => ({
      symbol: s.symbol,
      name: s.name,
    }));
    sessionStorage.setItem(key, JSON.stringify(dataToStore));
  } catch (err) {
    console.error(`Error saving ${key} to sessionStorage:`, err);
  }
};

interface CustomStoryResult {
  answer: string;
  articles: Array<{ id: number; ticker: string; title: string; summary?: string; url?: string; source?: string; published_at?: string }>;
  context_type?: string;
  macro_sources?: Array<{ topic: string; title?: string; as_of_date?: string }>;
  detected_tickers?: string[];
}

type AskMessage = { role: 'user' | 'assistant'; content: string; articles?: CustomStoryResult['articles']; contextType?: string; detectedTickers?: string[] };

const Dashboard: React.FC<DashboardProps> = ({ username, onLogout }) => {
  const { t } = useLocale();
  const [activeTab, setActiveTab] = useState<'Narrative' | 'Macro' | 'Ask' | 'Account'>(() => {
    if (typeof window !== 'undefined') {
      const p = new URLSearchParams(window.location.search);
      const tab = p.get('tab');
      if (tab === 'macro') return 'Macro';
      if (tab === 'ask') return 'Ask';
      if (tab === 'account') return 'Account';
      if (tab === 'narrative') return 'Narrative';
    }
    return 'Narrative';
  });
  const [currentView, setCurrentView] = useState<ViewType>('Portfolio');
  // Initialize from sessionStorage if available, otherwise use initial values
  const [portfolio, setPortfolio] = useState<Stock[]>(() => 
    loadFromSessionStorage(PORTFOLIO_STORAGE_KEY, INITIAL_PORTFOLIO)
  );
  const [watchlist, setWatchlist] = useState<Stock[]>(() => 
    loadFromSessionStorage(WATCHLIST_STORAGE_KEY, INITIAL_WATCHLIST)
  );
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearchVisible, setIsSearchVisible] = useState(false);
  const [suggestions, setSuggestions] = useState<StockInfo[]>([]);
  const [selectedStock, setSelectedStock] = useState<Stock | null>(null);
  const [nasdaq100Stocks, setNasdaq100Stocks] = useState<StockInfo[]>([]);
  const [loadingStocks, setLoadingStocks] = useState(false);
  const [storylineByTicker, setStorylineByTicker] = useState<Record<string, Array<{ title: string; summary?: string | null; last_updated_at?: string | null; story_type?: string | null }>>>({});
  const [overnightByTicker, setOvernightByTicker] = useState<Record<string, Array<{ id: string; title: string; summary?: string; last_updated_at: string | null; story_type: string; prediction?: string }>>>({});
  const [predictionByTicker, setPredictionByTicker] = useState<Record<string, string>>({});

  // Top-level Ask (question only; backend extracts tickers or macro from question)
  const [askQuestion, setAskQuestion] = useState('');
  const [askMessages, setAskMessages] = useState<AskMessage[]>([]);
  const [askLoading, setAskLoading] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const [askCooldownRemaining, setAskCooldownRemaining] = useState(0);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const searchContainerRef = useRef<HTMLDivElement>(null);
  const askChatScrollRef = useRef<HTMLDivElement>(null);
  const portfolioRef = useRef<Stock[]>(portfolio);
  const watchlistRef = useRef<Stock[]>(watchlist);
  portfolioRef.current = portfolio;
  watchlistRef.current = watchlist;

  const setTabAndCloseNav = (tab: 'Narrative' | 'Macro' | 'Ask' | 'Account') => {
    setActiveTab(tab);
    if (tab !== 'Account') setSelectedStock(null);
    setMobileNavOpen(false);
  };

  // Sync tab from URL on mount (e.g. link with ?tab=macro opens on Macro)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get('tab');
    if (tab === 'macro') setActiveTab('Macro');
    else if (tab === 'ask') setActiveTab('Ask');
    else if (tab === 'account') setActiveTab('Account');
    else if (tab === 'narrative') setActiveTab('Narrative');
    else if (!tab) setActiveTab('Narrative');
  }, []);

  // Cooldown timer: decrement every second when > 0
  useEffect(() => {
    if (askCooldownRemaining <= 0) return;
    const t = setInterval(() => {
      setAskCooldownRemaining((s) => (s <= 1 ? 0 : s - 1));
    }, 1000);
    return () => clearInterval(t);
  }, [askCooldownRemaining]);

  // Scroll Ask chat to bottom when messages change
  useEffect(() => {
    askChatScrollRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [askMessages, askLoading]);

  // Save portfolio to sessionStorage whenever it changes
  useEffect(() => {
    saveToSessionStorage(PORTFOLIO_STORAGE_KEY, portfolio);
  }, [portfolio]);

  // Save watchlist to sessionStorage whenever it changes
  useEffect(() => {
    saveToSessionStorage(WATCHLIST_STORAGE_KEY, watchlist);
  }, [watchlist]);

  const activeList = currentView === 'Portfolio' ? portfolio : watchlist;

  // Fetch storylines per ticker (title, summary, last_updated_at), API returns ordered by last_updated_at desc
  useEffect(() => {
    const tickers = activeList.map((s) => (s.symbol || '').trim().toUpperCase()).filter(Boolean);
    if (tickers.length === 0) {
      setStorylineByTicker({});
      return;
    }
    const abort = new AbortController();
    Promise.all(
      tickers.map((ticker) =>
        fetch(`${API_BASE}/storylines?ticker=${encodeURIComponent(ticker)}`, { signal: abort.signal })
          .then((res) => (res.ok ? res.json() : []))
          .then((data: Array<{ title?: string; canonical_theme?: string; summary?: string | null; last_updated_at?: string | null; story_type?: string | null }>) => {
            const list = Array.isArray(data) ? data : [];
            return {
              ticker,
              storylines: list.map((s) => ({
                title: s.title ?? s.canonical_theme ?? 'Story',
                summary: s.summary ?? null,
                last_updated_at: s.last_updated_at ?? null,
                story_type: s.story_type ?? null,
              })),
            };
          })
          .catch(() => ({ ticker, storylines: [] }))
      )
    ).then((results) => {
      const map: Record<string, Array<{ title: string; summary?: string | null; last_updated_at?: string | null; story_type?: string | null }>> = {};
      results.forEach(({ ticker, storylines }) => {
        map[ticker] = storylines;
      });
      setStorylineByTicker(map);
    });
    return () => abort.abort();
  }, [activeList]);

  // Fetch overnight stories per ticker (filter: session OVERNIGHT and expected move >= 1.2%, null excluded)
  // Time range: end = now; start = most recent business day 4pm America/New_York (client-computed via getOvernightWindowFallback)
  useEffect(() => {
    const tickers = activeList.map((s) => (s.symbol || '').trim().toUpperCase()).filter(Boolean);
    if (tickers.length === 0) {
      setOvernightByTicker({});
      setPredictionByTicker({});
      return;
    }
    const abort = new AbortController();
    type OvernightStoryRaw = {
      id: string;
      title?: string;
      summary?: string;
      session_label?: string;
      expected_abs_move_pct?: number | null;
      direction_bias?: string | null;
      risk_confidence?: number | null;
      latest_article_published_at?: string | null;
    };
    function weightedAveragePrediction(list: OvernightStoryRaw[]): string | null {
      const overnight = list.filter((s) => (s.session_label || '').toUpperCase() === 'OVERNIGHT');
      if (overnight.length === 0) return null;
      let weightedSum = 0;
      let totalWeight = 0;
      for (const s of overnight) {
        const dir = (s.direction_bias || '').toUpperCase();
        const sign = dir === 'UP' ? 1 : dir === 'DOWN' ? -1 : 0;
        const move = s.expected_abs_move_pct ?? 0;
        const weight = (s.risk_confidence != null && s.risk_confidence > 0) ? s.risk_confidence : 1;
        weightedSum += sign * move * weight;
        totalWeight += weight;
      }
      if (totalWeight <= 0) return null;
      const avgSigned = weightedSum / totalWeight;
      if (Math.abs(avgSigned) < 0.1) return 'Neutral';
      const pct = Math.abs(avgSigned).toFixed(1);
      return avgSigned > 0 ? `~${pct}% ↑` : `~${pct}% ↓`;
    }
    const { start: startStr, end: endStr } = getOvernightWindowFallback();
    const startDate = new Date(startStr);
    const endDate = new Date(endStr);
    Promise.all(
      tickers.map((ticker) =>
        fetch(`${API_BASE}/overnight-stories?ticker=${encodeURIComponent(ticker)}&start_date=${encodeURIComponent(startStr)}&end_date=${encodeURIComponent(endStr)}`, { signal: abort.signal })
          .then((res) => (res.ok ? res.json() : []))
          .then((data: OvernightStoryRaw[]) => {
            const list = Array.isArray(data) ? data : [];
            const filteredForPrediction = list.filter(
              (s) => {
                if ((s.session_label || '').toUpperCase() !== 'OVERNIGHT') return false;
                if (s.expected_abs_move_pct == null) return false;
                const pub = s.latest_article_published_at;
                if (!pub) return false;
                const pubDate = new Date(pub);
                if (pubDate < startDate || pubDate > endDate) return false;
                return true;
              }
            );
            const filtered = filteredForPrediction.filter((s) => (s.expected_abs_move_pct ?? 0) >= 1.2);
            const prediction = weightedAveragePrediction(filteredForPrediction);
            function storyPrediction(s: OvernightStoryRaw): string {
              const dir = (s.direction_bias || '').toUpperCase();
              const move = s.expected_abs_move_pct ?? 0;
              if (dir === 'UP') return `~${move.toFixed(1)}% ↑`;
              if (dir === 'DOWN') return `~${move.toFixed(1)}% ↓`;
              return 'Neutral';
            }
            return {
              ticker,
              stories: filtered.map((s) => ({
                id: s.id,
                title: (s.title || '').trim() || 'Overnight story',
                summary: s.summary,
                last_updated_at: s.latest_article_published_at ?? null,
                story_type: 'OVERNIGHT' as const,
                prediction: storyPrediction(s),
              })),
              prediction: prediction ?? undefined,
            };
          })
          .catch(() => ({ ticker, stories: [], prediction: undefined }))
      )
    )
      .then((results) => {
        const map: Record<string, Array<{ id: string; title: string; summary?: string; last_updated_at: string | null; story_type: string; prediction?: string }>> = {};
        const predictionMap: Record<string, string> = {};
        results.forEach(({ ticker, stories, prediction }) => {
          map[ticker] = stories;
          if (prediction) predictionMap[ticker] = prediction;
        });
        setOvernightByTicker(map);
        setPredictionByTicker(predictionMap);
      })
      .catch(() => {
        setOvernightByTicker({});
        setPredictionByTicker({});
      });
    return () => abort.abort();
  }, [activeList]);

  // All storylines table: story database only (overnight stories); same ticker grouped together
  const allStorylinesRows = React.useMemo(() => {
    const rows: Array<{ ticker: string; title: string; last_updated_at: string | null; prediction: string | null }> = [];
    activeList.forEach((stock) => {
      const ticker = (stock.symbol || '').trim().toUpperCase();
      const overnightList = overnightByTicker[ticker] ?? [];
      overnightList.forEach((s) => {
        rows.push({
          ticker,
          title: s.title,
          last_updated_at: s.last_updated_at,
          prediction: s.prediction ?? null,
        });
      });
    });
    // Group by ticker: sort by ticker then by last_updated_at desc
    rows.sort((a, b) => {
      const tickerCmp = (a.ticker || '').localeCompare(b.ticker || '');
      if (tickerCmp !== 0) return tickerCmp;
      const ta = a.last_updated_at ? new Date(a.last_updated_at).getTime() : 0;
      const tb = b.last_updated_at ? new Date(b.last_updated_at).getTime() : 0;
      return tb - ta;
    });
    return rows;
  }, [activeList, overnightByTicker]);

  // Fetch NASDAQ 100 stocks on mount
  useEffect(() => {
    setLoadingStocks(true);
    fetch(`${API_BASE}/stocks/nasdaq100`)
      .then((res) => (res.ok ? res.json() : Promise.reject(res)))
      .then((data: StockInfo[]) => {
        setNasdaq100Stocks(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        console.error('Error fetching NASDAQ 100 stocks:', err);
        setNasdaq100Stocks([]);
      })
      .finally(() => setLoadingStocks(false));
  }, []);

  // Fetch real stock prices from Alpaca via backend
  const fetchPrices = async (stocks: Stock[]): Promise<Stock[]> => {
    if (stocks.length === 0) return stocks;
    
    const symbols = stocks.map(s => s.symbol).join(',');
    try {
      const res = await fetch(`${API_BASE}/stocks/prices?symbols=${encodeURIComponent(symbols)}`);
      if (!res.ok) throw new Error('Failed to fetch prices');
      
      const prices: Array<{
        symbol: string;
        name: string;
        price: number;
        change: number;
        changePercent: number;
        extendedChange?: number | null;
        extendedChangePercent?: number | null;
      }> = await res.json();
      
      const priceMap = new Map(prices.map(p => [p.symbol, p]));
      
      return stocks.map(stock => {
        const priceData = priceMap.get(stock.symbol);
        if (priceData && priceData.price > 0) {
          return {
            ...stock,
            name: priceData.name || stock.name,
            price: priceData.price,
            change: priceData.change,
            changePercent: priceData.changePercent,
            extendedChange: priceData.extendedChange ?? null,
            extendedChangePercent: priceData.extendedChangePercent ?? null,
          };
        }
        return stock;
      });
    } catch (err) {
      console.error('Error fetching prices:', err);
      return stocks;
    }
  };

  // Fetch prices on mount and every 60s; use refs so interval always sees latest portfolio/watchlist
  useEffect(() => {
    const updatePrices = async () => {
      const currentPortfolio = portfolioRef.current;
      const currentWatchlist = watchlistRef.current;
      const updatedPortfolio = await fetchPrices(currentPortfolio);
      const updatedWatchlist = await fetchPrices(currentWatchlist);
      // Only update if prices actually changed (have real data)
      if (updatedPortfolio.some(s => s.price > 0)) {
        setPortfolio(updatedPortfolio);
      }
      if (updatedWatchlist.some(s => s.price > 0)) {
        setWatchlist(updatedWatchlist);
      }
    };
    updatePrices();
    const interval = setInterval(updatePrices, 60000);
    return () => clearInterval(interval);
  }, []); // Run once on mount
  
  // Fetch prices when stocks are added; use functional updates so we never overwrite with a shorter list (e.g. after add then navigate)
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      const needPortfolio = portfolio.some(s => s.price === 0);
      const needWatchlist = watchlist.some(s => s.price === 0);
      if (!needPortfolio && !needWatchlist) return;
      const updatedPortfolio = await fetchPrices(portfolio);
      const updatedWatchlist = await fetchPrices(watchlist);
      if (cancelled) return;
      if (updatedPortfolio.some(s => s.price > 0)) {
        setPortfolio((prev) => (updatedPortfolio.length >= prev.length ? updatedPortfolio : prev));
      }
      if (updatedWatchlist.some(s => s.price > 0)) {
        setWatchlist((prev) => (updatedWatchlist.length >= prev.length ? updatedWatchlist : prev));
      }
    };
    run();
    return () => { cancelled = true; };
  }, [portfolio.length, watchlist.length]); // Re-fetch when list changes

  useEffect(() => {
    if (searchQuery.length > 0 && nasdaq100Stocks.length > 0) {
      const filtered = nasdaq100Stocks.filter(s => 
        s.ticker.startsWith(searchQuery.toUpperCase()) || 
        s.name.toLowerCase().includes(searchQuery.toLowerCase())
      ).slice(0, 5);
      setSuggestions(filtered);
    } else {
      setSuggestions([]);
    }
  }, [searchQuery, nasdaq100Stocks]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (searchContainerRef.current && !searchContainerRef.current.contains(event.target as Node)) {
        setIsSearchVisible(false);
        setSuggestions([]);
        setSearchQuery('');
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleRemoveStock = (symbol: string) => {
    if (currentView === 'Portfolio') {
      setPortfolio((prev) => prev.filter(s => s.symbol !== symbol));
    } else {
      setWatchlist((prev) => prev.filter(s => s.symbol !== symbol));
    }
  };

  const addStockByData = (stockData: StockInfo) => {
    if (currentView === 'Portfolio') {
      setPortfolio((prev) => {
        if (prev.some(s => s.symbol === stockData.ticker)) return prev;
        const newStock: Stock = {
          symbol: stockData.ticker,
          name: stockData.name,
          price: 0,
          change: 0,
          changePercent: 0,
        };
        return [...prev, newStock];
      });
    } else {
      setWatchlist((prev) => {
        if (prev.some(s => s.symbol === stockData.ticker)) return prev;
        const newStock: Stock = {
          symbol: stockData.ticker,
          name: stockData.name,
          price: 0,
          change: 0,
          changePercent: 0,
        };
        return [...prev, newStock];
      });
    }
    setSearchQuery('');
    setSuggestions([]);
    setIsSearchVisible(false);
  };

  const handleManualAdd = () => {
    if (!searchQuery.trim()) return;
    const ticker = searchQuery.toUpperCase().trim();
    
    // Check if ticker is in NASDAQ 100 list
    const existing = nasdaq100Stocks.find(s => s.ticker === ticker);
    if (existing) {
      addStockByData(existing);
    } else {
      // Show error or warning - ticker not in NASDAQ 100
      alert(`Stock ${ticker} is not in NASDAQ 100 list. Please select from the suggestions.`);
    }
  };

  const ASK_COOLDOWN_SECONDS = 5;

  const handleAskSubmit = () => {
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
    // Send last 3 rounds (6 messages) as context for follow-up answers
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

  const handleAskClearChat = () => {
    setAskMessages([]);
    setAskError(null);
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Top Header */}
      <header className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-gray-900 bg-black z-50">
        <div className="flex items-center gap-4 md:gap-12">
          <span className="text-[#CCFF00] text-xl sm:text-2xl font-bold tracking-tighter cursor-pointer" onClick={() => setSelectedStock(null)}>{t('nav.morningEdge')}</span>

          {/* Desktop nav: Narrative | Macro | Ask | Account */}
          <nav className="hidden md:flex items-center gap-8">
            <button
              onClick={() => { setActiveTab('Narrative'); setSelectedStock(null); window.history.replaceState(null, '', '?tab=narrative'); }}
              className={`text-sm font-bold transition-colors pb-1 border-b-2 min-h-[44px] flex items-center ${activeTab === 'Narrative' ? 'border-[#CCFF00] text-[#CCFF00]' : 'border-transparent text-gray-500 hover:text-white'}`}
            >
              {t('nav.narrative')}
            </button>
            <button
              onClick={() => { setActiveTab('Macro'); setSelectedStock(null); window.history.replaceState(null, '', '?tab=macro'); }}
              className={`text-sm font-bold transition-colors pb-1 border-b-2 min-h-[44px] flex items-center ${activeTab === 'Macro' ? 'border-[#CCFF00] text-[#CCFF00]' : 'border-transparent text-gray-500 hover:text-white'}`}
            >
              {t('nav.macro')}
            </button>
            <button
              onClick={() => { setActiveTab('Ask'); setSelectedStock(null); window.history.replaceState(null, '', '?tab=ask'); }}
              className={`text-sm font-bold transition-colors pb-1 border-b-2 min-h-[44px] flex items-center ${activeTab === 'Ask' ? 'border-[#CCFF00] text-[#CCFF00]' : 'border-transparent text-gray-500 hover:text-white'}`}
            >
              {t('nav.ask')}
            </button>
            <button
              onClick={() => { setActiveTab('Account'); window.history.replaceState(null, '', '?tab=account'); }}
              className={`text-sm font-bold transition-colors pb-1 border-b-2 min-h-[44px] flex items-center ${activeTab === 'Account' ? 'border-[#CCFF00] text-[#CCFF00]' : 'border-transparent text-gray-500 hover:text-white'}`}
            >
              {t('nav.account')}
            </button>
          </nav>
        </div>

        <div className="flex items-center gap-2 sm:gap-4">
          <LanguageSwitcher className="hidden sm:flex" />
          <span className="hidden xs:inline text-xs font-bold text-gray-500">{t('nav.hi')}, {username.toUpperCase()}</span>
          <button onClick={onLogout} className="p-2.5 min-h-[44px] min-w-[44px] flex items-center justify-center text-gray-500 hover:text-white transition-colors rounded-lg" aria-label={t('nav.logout')}>
            <LogOut size={18} />
          </button>
          {/* Mobile: show current tab + hamburger so Macro/Ask/Account are discoverable */}
          <div className="md:hidden flex items-center gap-2">
            <span className="text-xs font-bold text-gray-500 uppercase tracking-wider" aria-hidden="true">{activeTab === 'Narrative' ? t('nav.narrative') : activeTab === 'Macro' ? t('nav.macro') : activeTab === 'Ask' ? t('nav.ask') : t('nav.account')}</span>
            <button
              type="button"
              onClick={() => setMobileNavOpen((o) => !o)}
              className="p-2.5 min-h-[44px] min-w-[44px] flex items-center justify-center text-gray-400 hover:text-white transition-colors rounded-lg border border-gray-800"
              aria-label="Open menu"
            >
              {mobileNavOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>
      </header>

      {/* Mobile nav overlay */}
      {mobileNavOpen && (
        <div className="md:hidden fixed inset-0 top-[57px] z-40 bg-black/95 border-t border-gray-800 flex flex-col">
          <nav className="flex flex-col p-4">
            <button onClick={() => setTabAndCloseNav('Narrative')} className={`text-left py-3 px-4 rounded-lg text-sm font-bold min-h-[44px] flex items-center ${activeTab === 'Narrative' ? 'bg-[#CCFF00]/10 text-[#CCFF00]' : 'text-gray-300 hover:bg-gray-800'}`}>
              {t('nav.narrative')}
            </button>
            <button onClick={() => setTabAndCloseNav('Macro')} className={`text-left py-3 px-4 rounded-lg text-sm font-bold min-h-[44px] flex items-center ${activeTab === 'Macro' ? 'bg-[#CCFF00]/10 text-[#CCFF00]' : 'text-gray-300 hover:bg-gray-800'}`}>
              {t('nav.macro')}
            </button>
            <button onClick={() => setTabAndCloseNav('Ask')} className={`text-left py-3 px-4 rounded-lg text-sm font-bold min-h-[44px] flex items-center ${activeTab === 'Ask' ? 'bg-[#CCFF00]/10 text-[#CCFF00]' : 'text-gray-300 hover:bg-gray-800'}`}>
              {t('nav.ask')}
            </button>
            <button onClick={() => setTabAndCloseNav('Account')} className={`text-left py-3 px-4 rounded-lg text-sm font-bold min-h-[44px] flex items-center ${activeTab === 'Account' ? 'bg-[#CCFF00]/10 text-[#CCFF00]' : 'text-gray-300 hover:bg-gray-800'}`}>
              {t('nav.account')}
            </button>
          </nav>
        </div>
      )}

      {/* Content Area */}
      <main className="flex-1 overflow-y-auto bg-black">
        {activeTab === 'Macro' ? (
          <MacroView />
        ) : activeTab === 'Ask' ? (
          <div className="flex flex-col h-full min-h-0 bg-black">
            {/* Top bar: clear chat only; context is extracted from question */}
            <div className="flex-shrink-0 px-4 sm:px-6 py-3 border-b border-gray-800 flex items-center justify-between">
              <p className="text-xs text-gray-500">{t('ask.topBarHint')}</p>
              {askMessages.length > 0 && (
                <button type="button" onClick={handleAskClearChat} className="text-xs font-medium text-gray-500 hover:text-gray-300 flex items-center gap-1.5" aria-label="Clear chat">
                  <Trash2 size={14} /> Clear chat
                </button>
              )}
            </div>

            {/* Scrollable message area (centered column like ChatGPT) */}
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

            {/* Bottom input bar (ChatGPT-style: single rounded box) */}
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
                    onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); handleAskSubmit(); } }}
                  />
                  <button
                    type="button"
                    onClick={handleAskSubmit}
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
        ) : activeTab === 'Narrative' ? (
          selectedStock ? (
            <div className="animate-in fade-in duration-300">
               <div className="px-4 sm:px-6 md:px-8 py-4 bg-[#0a0a0a] border-b border-gray-900 flex items-center gap-4">
                  <button onClick={() => setSelectedStock(null)} className="p-2 hover:bg-gray-800 rounded-full text-gray-400 transition-colors">
                    <ArrowLeft size={20} />
                  </button>
                  <div>
                    <h2 className="text-2xl font-bold tracking-tight">{selectedStock.symbol} <span className="text-gray-500 font-medium text-lg ml-2">{selectedStock.name}</span></h2>
                  </div>
               </div>
               <StockDetail stock={selectedStock} />
            </div>
          ) : (
            <div className="max-w-6xl mx-auto p-4 sm:p-6 md:p-8">
              {/* Toolbar */}
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
                <div className="relative">
                  <button 
                    onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                    className="flex items-center gap-2 text-3xl font-bold hover:text-[#CCFF00] transition-colors"
                  >
                    {currentView === 'Portfolio' ? t('narrative.myPortfolio') : t('narrative.myWatchList')}
                    <ChevronDown size={28} className={`transition-transform ${isDropdownOpen ? 'rotate-180' : ''}`} />
                  </button>
                  
                  {isDropdownOpen && (
                    <div className="absolute top-full left-0 mt-2 w-56 bg-[#121212] border border-gray-800 rounded-lg shadow-2xl z-40 overflow-hidden">
                      <button 
                        onClick={() => { setCurrentView('Portfolio'); setIsDropdownOpen(false); }}
                        className="w-full text-left px-4 py-3 hover:bg-[#1a1a1a] transition-colors font-medium"
                      >
                        {t('narrative.myPortfolio')}
                      </button>
                      <button 
                        onClick={() => { setCurrentView('Watchlist'); setIsDropdownOpen(false); }}
                        className="w-full text-left px-4 py-3 hover:bg-[#1a1a1a] transition-colors font-medium"
                      >
                        {t('narrative.myWatchList')}
                      </button>
                    </div>
                  )}
                </div>

                <div className="relative" ref={searchContainerRef}>
                  {isSearchVisible ? (
                    <>
                      <div className="flex items-center bg-[#121212] rounded-full px-4 py-2 border border-gray-800 animate-in fade-in slide-in-from-right-2">
                        <input 
                          type="text" 
                          autoFocus
                          placeholder={t('narrative.addTickerPlaceholder')}
                          className="bg-transparent outline-none text-sm w-32 md:w-48"
                          value={searchQuery}
                          onChange={(e) => setSearchQuery(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && handleManualAdd()}
                        />
                        <button onClick={handleManualAdd} className="text-[#CCFF00] ml-2">
                          <Plus size={18} />
                        </button>
                      </div>

                      {suggestions.length > 0 && (
                        <div className="absolute top-full right-0 mt-2 w-full min-w-[200px] bg-[#121212] border border-gray-800 rounded-lg shadow-2xl z-40 overflow-hidden">
                          {suggestions.map((s) => (
                            <button 
                              key={s.ticker}
                              onClick={() => addStockByData(s)}
                              className="w-full text-left px-4 py-3 hover:bg-[#1a1a1a] transition-colors border-b border-gray-900 last:border-0"
                            >
                              <div className="flex items-center justify-between">
                                <span className="font-bold text-[#CCFF00]">{s.ticker}</span>
                                <span className="text-xs text-gray-500 truncate ml-2">{s.name}</span>
                              </div>
                            </button>
                          ))}
                        </div>
                      )}
                    </>
                  ) : (
                    <button 
                      onClick={() => setIsSearchVisible(true)}
                      className="flex items-center gap-2 px-4 py-2 rounded-full border border-gray-800 hover:border-gray-600 transition-colors text-gray-400"
                    >
                      <Search size={16} />
                      <span className="text-sm font-medium">{t('narrative.addStock')}</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Grid Display */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                {activeList.map((stock) => {
                  const ticker = (stock.symbol || '').trim().toUpperCase();
                  const prediction = predictionByTicker[ticker];
                  return (
                    <StockCard
                      key={stock.symbol}
                      stock={stock}
                      onRemove={() => handleRemoveStock(stock.symbol)}
                      onClick={() => setSelectedStock(stock)}
                      storylineTitle={prediction ?? null}
                      storylineType={null}
                    />
                  );
                })}
                
                {activeList.length === 0 && (
                  <div className="col-span-full py-20 text-center border-2 border-dashed border-gray-900 rounded-xl">
                    <p className="text-gray-500 font-medium">{t('narrative.noStocksInList')}</p>
                  </div>
                )}
              </div>

              {/* Table-like layout: all storylines (title, ticker, time) */}
              {allStorylinesRows.length > 0 && (
                <div className="mt-10 border border-gray-800 rounded-xl bg-[#0a0a0a] overflow-hidden">
                  <div className="px-4 py-3 border-b border-gray-800">
                    <h3 className="text-sm font-bold text-gray-300 uppercase tracking-wider">{t('narrative.highImpactOvernight')}</h3>
                    <p className="text-xs text-gray-500 mt-0.5">{t('narrative.expectedMoveAtOpen')}</p>
                  </div>
                  <div className="divide-y divide-gray-800">
                    {allStorylinesRows.map((row, i) => {
                      const stock = activeList.find((s) => (s.symbol || '').trim().toUpperCase() === row.ticker);
                      const dateStr = row.last_updated_at
                        ? (() => {
                            const d = new Date(row.last_updated_at);
                            const now = new Date();
                            const isToday = d.toDateString() === now.toDateString();
                            const isYesterday = new Date(now.getTime() - 864e5).toDateString() === d.toDateString();
                            const time24 = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
                            if (isToday) return `Today, ${time24}`;
                            if (isYesterday) return `Yesterday, ${time24}`;
                            return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) + ', ' + time24;
                          })()
                        : '—';
                      return (
                        <button
                          key={`${row.ticker}-${i}`}
                          type="button"
                          onClick={() => stock && setSelectedStock(stock)}
                          className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-gray-800/50 transition-colors"
                        >
                          <div className="flex-shrink-0 min-w-[2.25rem] h-9 px-2 rounded-lg bg-gray-800 flex items-center justify-center">
                            <span className="text-xs font-bold text-[#CCFF00] whitespace-nowrap">{row.ticker || ''}</span>
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <p className="text-sm font-semibold text-white leading-tight underline decoration-gray-600 hover:decoration-[#CCFF00]">
                                {row.title}
                              </p>
                              {row.prediction && (() => {
                                const style = getPredictionStyle(row.prediction);
                                return (
                                  <span
                                    className="px-2 py-0.5 rounded text-[10px] font-bold tracking-wider border"
                                    style={{ color: style.color, backgroundColor: style.bg, borderColor: style.border }}
                                  >
                                    {row.prediction}
                                  </span>
                                );
                              })()}
                            </div>
                            <p className="text-xs text-gray-500 mt-1">
                              {row.ticker}
                              <span className="mx-1.5">·</span>
                              {dateStr}
                            </p>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )
        ) : activeTab === 'Account' ? (
          <div className="max-w-6xl mx-auto flex items-center justify-center h-64 border border-gray-800 rounded-xl bg-[#050505] mt-4 sm:mt-6 md:mt-8 px-4 sm:px-6 md:px-8">
            <div className="text-center">
              <h3 className="text-xl font-bold mb-2">{t('account.feature')}</h3>
              <p className="text-gray-500">{t('account.underDevelopment')}</p>
            </div>
          </div>
        ) : null}
      </main>
    </div>
  );
};

export default Dashboard;
