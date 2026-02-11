import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { createChart, IChartApi, CandlestickSeries, HistogramSeries, ColorType, ISeriesApi } from 'lightweight-charts';
import { Stock } from '../types';
import { API_BASE } from '../api';

interface CandlestickData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface VolumeData {
  time: number;
  value: number;
  color: string;
}

interface TradingViewChartProps {
  stock: Stock;
  timeframe: string;
}

// Available timeframe options (time range to display)
const TIMEFRAME_OPTIONS = [
  { value: '1D', label: '1 Day', days: 1 },
  { value: '2D', label: '2 Days', days: 2 },
  { value: '3D', label: '3 Days', days: 3 },
  { value: '1W', label: '1 Week', days: 7 },
  { value: '1M', label: '1 Month', days: 30 },
  { value: '3M', label: '3 Months', days: 90 },
  { value: '6M', label: '6 Months', days: 180 },
  { value: '1Y', label: '1 Year', days: 365 },
];

// Available interval options (candlestick interval) - supported by Alpaca
const INTERVAL_OPTIONS = [
  { value: '1Min', label: '1 Min' },
  { value: '5Min', label: '5 Min' },
  { value: '15Min', label: '15 Min' },
  { value: '30Min', label: '30 Min' },
  { value: '1Hour', label: '1 Hour' },
  { value: '4Hour', label: '4 Hour' },
  { value: '1Day', label: '1 Day' },
  { value: '1Week', label: '1 Week' },
];

// Convert UTC Unix timestamp to local time for chart display.
// lightweight-charts treats timestamps as UTC; shifting by the browser's
// timezone offset makes the x-axis show the user's local time.
const utcToLocal = (utcTs: number): number => {
  const offsetSec = new Date(utcTs * 1000).getTimezoneOffset() * 60;
  return utcTs - offsetSec;
};

// Reverse: convert a local-display timestamp back to UTC for API calls.
const localToUtc = (localTs: number): number => {
  const offsetSec = new Date(localTs * 1000).getTimezoneOffset() * 60;
  return localTs + offsetSec;
};

const TradingViewChart: React.FC<TradingViewChartProps> = ({ stock, timeframe: initialTimeframe }) => {
  const priceChartContainerRef = useRef<HTMLDivElement>(null);
  const volumeChartContainerRef = useRef<HTMLDivElement>(null);
  const priceChartRef = useRef<IChartApi | null>(null);
  const volumeChartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const [bars, setBars] = useState<CandlestickData[]>([]);
  const [volumeData, setVolumeData] = useState<VolumeData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const earliestLoadedRef = useRef<number | null>(null);
  const isLoadingMoreRef = useRef(false);
  const loadMoreDataRef = useRef<((endTimestamp: number) => Promise<void>) | null>(null);
  // Track what settings the current chart was created with
  const chartSettingsRef = useRef<string>('');
  // Track what settings the current DATA was fetched for - use state to trigger re-render
  const [dataSettings, setDataSettings] = useState<string>('');
  
  // Local state for timeframe and interval controls
  const [selectedTimeframe, setSelectedTimeframe] = useState(initialTimeframe);
  const [selectedInterval, setSelectedInterval] = useState('5Min');
  
  // 21-day average daily volume
  const [avgDailyVolume21, setAvgDailyVolume21] = useState<number | null>(null);
  
  // Track visible range for calculating stats from visible bars only
  const [visibleRange, setVisibleRange] = useState<{ from: number; to: number } | null>(null);

  // Get a sensible default interval based on timeframe
  const getDefaultInterval = (tf: string): string => {
    switch (tf) {
      case '1D': return '5Min';
      case '2D': return '15Min';
      case '3D': return '15Min';
      case '1W': return '1Hour';
      case '1M': return '4Hour';
      case '3M': return '1Day';
      case '6M': return '1Day';
      case '1Y': return '1Day';
      default: return '5Min';
    }
  };

  // Sync with parent's timeframe when it changes
  useEffect(() => {
    if (initialTimeframe !== selectedTimeframe) {
      setSelectedTimeframe(initialTimeframe);
      setSelectedInterval(getDefaultInterval(initialTimeframe));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialTimeframe]);

  const upColor = '#CCFF00';
  const downColor = '#ff5000';

  // Get days from selected timeframe
  const getTimeframeDays = (tf: string): number => {
    const option = TIMEFRAME_OPTIONS.find(o => o.value === tf);
    return option?.days ?? 1;
  };

  // Get the API timeframe config based on selected interval and timeframe
  const getTimeframeConfig = (): { apiTimeframe: string; days: number } => {
    return { 
      apiTimeframe: selectedInterval, 
      days: getTimeframeDays(selectedTimeframe) 
    };
  };

  // Helper to create volume data from bars
  const createVolumeData = useCallback((barsData: CandlestickData[]): VolumeData[] => {
    return barsData.map((bar, index) => {
      const isUp = index === 0 ? bar.close >= bar.open : bar.close >= barsData[index - 1].close;
      return {
        time: bar.time,
        value: bar.volume || 0,
        color: isUp ? 'rgba(204, 255, 0, 0.5)' : 'rgba(255, 80, 0, 0.5)',
      };
    });
  }, []);

  // Load more historical data
  const loadMoreData = useCallback(async (endTimestamp: number) => {
    if (isLoadingMoreRef.current) return;
    isLoadingMoreRef.current = true;
    setLoadingMore(true);

    const { apiTimeframe } = getTimeframeConfig();
    // Use more days for historical loading to skip weekends/holidays
    const historicalDays = 7;

    try {
      // endTimestamp is in local display time; convert back to UTC for API
      const utcEndTs = localToUtc(endTimestamp);
      const res = await fetch(
        `${API_BASE}/stocks/bars?symbol=${encodeURIComponent(stock.symbol)}&timeframe=${apiTimeframe}&days=${historicalDays}&end_ts=${utcEndTs}`
      );

      if (!res.ok) {
        throw new Error('Failed to fetch more data');
      }

      const data = await res.json();

      if (data.bars && data.bars.length > 0) {
        const newBars: CandlestickData[] = data.bars.map((bar: any) => ({
          time: utcToLocal(Number(bar.time)),
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
          volume: bar.volume || 0,
        }));

        // Filter out bars we already have
        const existingTimes = new Set(bars.map(b => b.time));
        const uniqueNewBars = newBars.filter(b => !existingTimes.has(b.time));

        if (uniqueNewBars.length > 0) {
          // Prepend new bars and sort by time
          const allBars = [...uniqueNewBars, ...bars].sort((a, b) => a.time - b.time);
          setBars(allBars);

          // Update volume data
          const allVolumeData = createVolumeData(allBars);
          setVolumeData(allVolumeData);

          // Update earliest loaded timestamp
          earliestLoadedRef.current = allBars[0].time;

          // Update series data directly if available
          if (candlestickSeriesRef.current) {
            candlestickSeriesRef.current.setData(allBars as any);
          }
          if (volumeSeriesRef.current) {
            volumeSeriesRef.current.setData(allVolumeData as any);
          }
        }
      }
    } catch (err) {
      console.error('Error loading more data:', err);
    } finally {
      isLoadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [stock.symbol, selectedTimeframe, selectedInterval, bars, createVolumeData]);

  // Store loadMoreData in ref to avoid dependency issues in useEffect
  loadMoreDataRef.current = loadMoreData;

  // Fetch bar data from API
  useEffect(() => {
    const fetchBars = async () => {
      setLoading(true);
      setError(null);

      const { apiTimeframe, days } = getTimeframeConfig();

      try {
        const res = await fetch(
          `${API_BASE}/stocks/bars?symbol=${encodeURIComponent(stock.symbol)}&timeframe=${apiTimeframe}&days=${days}`
        );

        if (!res.ok) {
          throw new Error('Failed to fetch chart data');
        }

        const data = await res.json();
        
        if (data.bars && data.bars.length > 0) {
          // Convert string time to number and shift to local timezone
          const formattedBars: CandlestickData[] = data.bars.map((bar: any) => ({
            time: utcToLocal(Number(bar.time)),
            open: bar.open,
            high: bar.high,
            low: bar.low,
            close: bar.close,
            volume: bar.volume || 0,
          }));
          
          // Track earliest loaded timestamp
          earliestLoadedRef.current = formattedBars[0].time;

          // Create volume data with colors based on price direction
          const formattedVolume: VolumeData[] = createVolumeData(formattedBars);
          
          // Set all data FIRST, then set dataSettings LAST to trigger chart effect
          // This ensures chart effect sees the correct bars and volumeData
          setBars(formattedBars);
          setVolumeData(formattedVolume);
          
          // Mark what settings this data is for - this triggers chart creation
          const newDataSettings = `${stock.symbol}-${selectedTimeframe}-${selectedInterval}`;
          setDataSettings(newDataSettings);
        } else {
          setBars([]);
          setVolumeData([]);
          earliestLoadedRef.current = null;
        }
      } catch (err) {
        console.error('Error fetching bars:', err);
        setError('Unable to load chart data');
      } finally {
        setLoading(false);
      }
    };

    fetchBars();
  }, [stock.symbol, selectedTimeframe, selectedInterval]);

  // Fetch 21-day average daily volume (independent of timeframe/interval)
  useEffect(() => {
    const fetch21DayVolume = async () => {
      try {
        // Fetch 30 days of daily bars to ensure we get at least 21 trading days
        const res = await fetch(
          `${API_BASE}/stocks/bars?symbol=${encodeURIComponent(stock.symbol)}&timeframe=1Day&days=30`
        );

        if (!res.ok) {
          console.error('Failed to fetch 21-day volume data');
          return;
        }

        const data = await res.json();
        
        if (data.bars && data.bars.length > 0) {
          // Take up to 21 most recent trading days
          const recentBars = data.bars.slice(-21);
          const totalVolume = recentBars.reduce((sum: number, bar: any) => sum + (bar.volume || 0), 0);
          const avgVolume = totalVolume / recentBars.length;
          setAvgDailyVolume21(avgVolume);
        }
      } catch (err) {
        console.error('Error fetching 21-day volume:', err);
      }
    };

    fetch21DayVolume();
  }, [stock.symbol]); // Only refetch when symbol changes

  // Create charts (only when symbol/timeframe changes or initial mount with data)
  // Use refs to store cleanup functions that need to be called
  const cleanupFunctionsRef = useRef<{ unsubscribe?: () => void; removeResizeListener?: () => void }>({});
  
  useEffect(() => {
    const currentSettings = `${stock.symbol}-${selectedTimeframe}-${selectedInterval}`;
    const dataMatchesSettings = dataSettings === currentSettings;
    const chartMatchesSettings = chartSettingsRef.current === currentSettings;
    
    // Don't create chart if no data or data is stale (for different settings)
    if (bars.length === 0 || !dataMatchesSettings) {
      return;
    }
    
    // If chart already exists for SAME settings, skip recreation
    if (priceChartRef.current && candlestickSeriesRef.current && chartMatchesSettings) {
      return;
    }
    
    // Clean up any previous event listeners before creating new charts
    if (cleanupFunctionsRef.current.unsubscribe) {
      cleanupFunctionsRef.current.unsubscribe();
    }
    if (cleanupFunctionsRef.current.removeResizeListener) {
      cleanupFunctionsRef.current.removeResizeListener();
    }
    cleanupFunctionsRef.current = {};
    
    // Use requestAnimationFrame to defer chart creation until AFTER React Strict Mode's
    // unmount/remount cycle completes. This ensures we create charts in the final stable DOM.
    let cancelled = false;
    
    const rafId = requestAnimationFrame(() => {
      // Check if cleanup was called before RAF executed
      if (cancelled) {
        return;
      }
      
      // Re-check containers are available (they should be stable now after React settles)
      if (!priceChartContainerRef.current || !volumeChartContainerRef.current) {
        return;
      }

      // Clean up existing charts before creating new ones
      if (priceChartRef.current) {
        try { priceChartRef.current.remove(); } catch (e) { /* ignore */ }
        priceChartRef.current = null;
      }
      if (volumeChartRef.current) {
        try { volumeChartRef.current.remove(); } catch (e) { /* ignore */ }
        volumeChartRef.current = null;
      }
      candlestickSeriesRef.current = null;
      volumeSeriesRef.current = null;
      
      // Clear container innerHTML to ensure clean slate (remove any leftover DOM elements)
      if (priceChartContainerRef.current) {
        priceChartContainerRef.current.innerHTML = '';
      }
      if (volumeChartContainerRef.current) {
        volumeChartContainerRef.current.innerHTML = '';
      }
      
      // Update settings ref to track what we're creating for
      chartSettingsRef.current = currentSettings;

      // Common chart options
      const commonOptions = {
        layout: {
          background: { type: ColorType.Solid, color: '#080808' },
          textColor: '#666666',
        },
        grid: {
          vertLines: { color: '#1a1a1a' },
          horzLines: { color: '#1a1a1a' },
        },
        crosshair: {
          mode: 1 as const,
          vertLine: {
            color: '#CCFF00',
            width: 1 as const,
            style: 2 as const,
            labelBackgroundColor: '#CCFF00',
          },
          horzLine: {
            color: '#CCFF00',
            width: 1 as const,
            style: 2 as const,
            labelBackgroundColor: '#CCFF00',
          },
        },
        rightPriceScale: {
          borderColor: '#2a2a2a',
          scaleMargins: {
            top: 0.05,
            bottom: 0.05,
          },
          minimumWidth: 80, // Fixed width for alignment
        },
      };
      
      // Create PRICE chart (hide time scale - it will show on volume chart below)
      const priceChart = createChart(priceChartContainerRef.current!, {
        ...commonOptions,
        width: priceChartContainerRef.current!.clientWidth,
        height: 350,
        timeScale: {
          borderColor: '#2a2a2a',
          visible: false, // Hide time scale on price chart
        },
      });

      priceChartRef.current = priceChart;

      // Add candlestick series for price
      const candlestickSeries = priceChart.addSeries(CandlestickSeries, {
        upColor: upColor,
        downColor: downColor,
        borderUpColor: upColor,
        borderDownColor: downColor,
        wickUpColor: upColor,
        wickDownColor: downColor,
      });

      candlestickSeries.setData(bars as any);
      candlestickSeriesRef.current = candlestickSeries;
      priceChart.timeScale().fitContent();

      // Create VOLUME chart
      const volumeChart = createChart(volumeChartContainerRef.current!, {
        ...commonOptions,
        width: volumeChartContainerRef.current!.clientWidth,
        height: 150,
        timeScale: {
          borderColor: '#2a2a2a',
          timeVisible: true,
          secondsVisible: false,
          visible: true,
        },
      });

      volumeChartRef.current = volumeChart;

      // Add volume histogram series
      const volumeSeries = volumeChart.addSeries(HistogramSeries, {
        priceFormat: {
          type: 'volume',
        },
      });

      volumeSeries.setData(volumeData as any);
      volumeSeriesRef.current = volumeSeries;
      volumeChart.timeScale().fitContent();

      // Synchronize time scales between the two charts and track visible range for stats
      const syncTimeScales = () => {
        const priceTimeScale = priceChart.timeScale();
        const volumeTimeScale = volumeChart.timeScale();

        priceTimeScale.subscribeVisibleLogicalRangeChange((range) => {
          if (range) {
            volumeTimeScale.setVisibleLogicalRange(range);
            // Update visible range state for stats calculation
            setVisibleRange({ from: Math.floor(range.from), to: Math.ceil(range.to) });
          }
        });

        volumeTimeScale.subscribeVisibleLogicalRangeChange((range) => {
          if (range) {
            priceTimeScale.setVisibleLogicalRange(range);
          }
        });
      };

      syncTimeScales();
      
      // Set initial visible range after chart is created
      const initialRange = priceChart.timeScale().getVisibleLogicalRange();
      if (initialRange) {
        setVisibleRange({ from: Math.floor(initialRange.from), to: Math.ceil(initialRange.to) });
      }

      // Detect when user scrolls to the edge and load more data
      // Skip initial render to prevent immediate loading
      let isFirstRangeChange = true;
      
      const handleVisibleRangeChange = (logicalRange: { from: number; to: number } | null) => {
        // Skip the first range change (happens on chart creation)
        if (isFirstRangeChange) {
          isFirstRangeChange = false;
          return;
        }
        
        if (!logicalRange || isLoadingMoreRef.current) return;

        // If user scrolled to see bars at index < 5, load more historical data
        if (logicalRange.from < 5 && earliestLoadedRef.current && loadMoreDataRef.current) {
          loadMoreDataRef.current(earliestLoadedRef.current);
        }
      };

      const unsubscribe = priceChart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleRangeChange);

      // Handle resize
      const handleResize = () => {
        if (priceChartContainerRef.current && priceChartRef.current) {
          priceChartRef.current.applyOptions({
            width: priceChartContainerRef.current.clientWidth,
          });
        }
        if (volumeChartContainerRef.current && volumeChartRef.current) {
          volumeChartRef.current.applyOptions({
            width: volumeChartContainerRef.current.clientWidth,
          });
        }
      };

      window.addEventListener('resize', handleResize);
      
      // Store cleanup functions in ref so they can be called on next effect run or unmount
      cleanupFunctionsRef.current = {
        unsubscribe,
        removeResizeListener: () => window.removeEventListener('resize', handleResize),
      };
    }); // End of RAF callback

    // Cleanup: cancel RAF if pending
    return () => {
      // Mark as cancelled so RAF callback knows to skip
      cancelled = true;
      cancelAnimationFrame(rafId);
      
      // Note: We don't clean up event listeners here because they're stored in cleanupFunctionsRef
      // and will be cleaned up at the start of the next effect run or on unmount
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataSettings]); // Only run when fresh data arrives (dataSettings changes)
  
  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (cleanupFunctionsRef.current.unsubscribe) {
        cleanupFunctionsRef.current.unsubscribe();
      }
      if (cleanupFunctionsRef.current.removeResizeListener) {
        cleanupFunctionsRef.current.removeResizeListener();
      }
    };
  }, []);

  // Update chart data when bars/volumeData change (without recreating chart)
  useEffect(() => {
    if (bars.length === 0) return;
    
    // Update series data if charts exist
    if (candlestickSeriesRef.current) {
      candlestickSeriesRef.current.setData(bars as any);
    }
    if (volumeSeriesRef.current) {
      volumeSeriesRef.current.setData(volumeData as any);
    }
    
    // Fit content after data update
    if (priceChartRef.current) {
      priceChartRef.current.timeScale().fitContent();
    }
    if (volumeChartRef.current) {
      volumeChartRef.current.timeScale().fitContent();
    }
  }, [bars, volumeData]);

  // Get bars that are currently visible in the chart window
  const visibleBars = useMemo(() => {
    if (bars.length === 0 || !visibleRange) {
      return bars;
    }
    
    // The visible range is in logical coordinates (bar indices)
    const fromIndex = Math.max(0, visibleRange.from);
    const toIndex = Math.min(bars.length, visibleRange.to + 1);
    
    return bars.slice(fromIndex, toIndex);
  }, [bars, visibleRange]);

  // Market price is always the latest price (from all bars)
  const latestPrice = useMemo(() => {
    if (bars.length === 0) {
      return stock.price;
    }
    return bars[bars.length - 1].close;
  }, [bars, stock.price]);

  // Calculate return (change/changePercent) from VISIBLE bar data only
  const visibleReturn = useMemo(() => {
    if (visibleBars.length === 0) {
      return {
        change: stock.change,
        changePercent: stock.changePercent,
      };
    }
    
    // Get the last visible bar's close and first visible bar's open
    const lastVisibleClose = visibleBars[visibleBars.length - 1].close;
    const firstVisibleOpen = visibleBars[0].open;
    
    // Calculate change within visible range
    const change = lastVisibleClose - firstVisibleOpen;
    const changePercent = firstVisibleOpen > 0 ? (change / firstVisibleOpen) * 100 : 0;
    
    return {
      change: change,
      changePercent: changePercent,
    };
  }, [visibleBars, stock.change, stock.changePercent]);

  return (
    <div className="w-full">
      {/* Price header */}
      <div className="flex items-end justify-between mb-6">
        <div>
          <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1">
            Market Price
          </div>
          <div className="flex items-baseline gap-4">
            <h2 className="text-4xl font-bold tracking-tighter">
              ${latestPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </h2>
            <span className={`text-sm font-bold ${visibleReturn.change >= 0 ? 'text-[#CCFF00]' : 'text-[#ff5000]'}`}>
              {visibleReturn.change >= 0 ? '+' : ''}{visibleReturn.change.toFixed(2)} ({visibleReturn.changePercent.toFixed(2)}%)
            </span>
          </div>
        </div>
        
        {/* Timeframe and Interval Controls */}
        <div className="flex items-center gap-4">
          {/* Timeframe Dropdown */}
          <div>
            <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1">
              Timeframe
            </div>
            <select
              value={selectedTimeframe}
              onChange={(e) => {
                const newTimeframe = e.target.value;
                setSelectedTimeframe(newTimeframe);
                setSelectedInterval(getDefaultInterval(newTimeframe));
              }}
              className="bg-[#0a0a0a] border border-gray-800 rounded-lg px-3 py-1.5 text-sm font-bold text-white focus:outline-none focus:border-[#CCFF00] cursor-pointer appearance-none min-w-[100px]"
              style={{
                backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%23666'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M19 9l-7 7-7-7'%3E%3C/path%3E%3C/svg%3E")`,
                backgroundRepeat: 'no-repeat',
                backgroundPosition: 'right 8px center',
                backgroundSize: '16px',
                paddingRight: '32px',
              }}
            >
              {TIMEFRAME_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          {/* Interval Dropdown */}
          <div>
            <div className="text-[10px] font-bold text-gray-500 uppercase tracking-widest mb-1">
              Interval
            </div>
            <select
              value={selectedInterval}
              onChange={(e) => {
                setSelectedInterval(e.target.value);
              }}
              className="bg-[#0a0a0a] border border-gray-800 rounded-lg px-3 py-1.5 text-sm font-bold text-white focus:outline-none focus:border-[#CCFF00] cursor-pointer appearance-none min-w-[100px]"
              style={{
                backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%23666'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M19 9l-7 7-7-7'%3E%3C/path%3E%3C/svg%3E")`,
                backgroundRepeat: 'no-repeat',
                backgroundPosition: 'right 8px center',
                backgroundSize: '16px',
                paddingRight: '32px',
              }}
            >
              {INTERVAL_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Loading / Error states */}
      {loading && (
        <div className="w-full bg-[#080808] rounded-xl border border-gray-900 overflow-hidden" style={{ height: 520 }}>
          <div className="h-full flex items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 border-2 border-[#CCFF00] border-t-transparent rounded-full animate-spin" />
              <span className="text-xs font-bold text-gray-500 uppercase tracking-widest">
                Loading chart...
              </span>
            </div>
          </div>
        </div>
      )}

      {error && !loading && (
        <div className="w-full bg-[#080808] rounded-xl border border-gray-900 overflow-hidden" style={{ height: 520 }}>
          <div className="h-full flex items-center justify-center">
            <span className="text-xs font-bold text-gray-500 uppercase tracking-widest">
              {error}
            </span>
          </div>
        </div>
      )}

      {!loading && bars.length === 0 && !error && (
        <div className="w-full bg-[#080808] rounded-xl border border-gray-900 overflow-hidden" style={{ height: 520 }}>
          <div className="h-full flex items-center justify-center">
            <span className="text-xs font-bold text-gray-500 uppercase tracking-widest">
              No data available
            </span>
          </div>
        </div>
      )}

      {/* Charts Container */}
      <div className={`${loading || error || bars.length === 0 ? 'hidden' : ''}`}>
        <div className="w-full bg-[#080808] rounded-xl border border-gray-900 overflow-hidden relative">
          {/* Loading more indicator */}
          {loadingMore && (
            <div className="absolute top-3 right-4 z-20 flex items-center gap-2">
              <div className="w-3 h-3 border border-[#CCFF00] border-t-transparent rounded-full animate-spin" />
              <span className="text-[9px] font-bold text-gray-500 uppercase tracking-widest">
                Loading more...
              </span>
            </div>
          )}
          
          {/* Price Chart */}
          <div className="relative w-full border-b border-gray-900">
            <div className="absolute top-3 left-4 z-10">
              <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">
                Price (USD)
              </span>
            </div>
            <div 
              ref={priceChartContainerRef} 
              style={{ height: 350 }}
            />
          </div>

          {/* Volume Chart */}
          <div className="relative w-full">
            <div className="absolute top-3 left-4 z-10">
              <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">
                Volume
              </span>
            </div>
            <div 
              ref={volumeChartContainerRef} 
              style={{ height: 150 }}
            />
          </div>
        </div>
      </div>

      {/* Stats grid - calculated from visible bars only */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mt-6">
        {visibleBars.length > 0 && (
          <>
            <div className="bg-[#0a0a0a] border border-gray-900 p-4 rounded-xl">
              <div className="text-[9px] font-bold text-gray-600 uppercase tracking-widest mb-1">Open</div>
              <div className="text-sm font-bold text-white">
                ${visibleBars[0]?.open?.toFixed(2) ?? '-'}
              </div>
            </div>
            <div className="bg-[#0a0a0a] border border-gray-900 p-4 rounded-xl">
              <div className="text-[9px] font-bold text-gray-600 uppercase tracking-widest mb-1">High</div>
              <div className="text-sm font-bold text-[#CCFF00]">
                ${Math.max(...visibleBars.map(b => b.high)).toFixed(2)}
              </div>
            </div>
            <div className="bg-[#0a0a0a] border border-gray-900 p-4 rounded-xl">
              <div className="text-[9px] font-bold text-gray-600 uppercase tracking-widest mb-1">Low</div>
              <div className="text-sm font-bold text-[#ff5000]">
                ${Math.min(...visibleBars.map(b => b.low)).toFixed(2)}
              </div>
            </div>
            <div className="bg-[#0a0a0a] border border-gray-900 p-4 rounded-xl">
              <div className="text-[9px] font-bold text-gray-600 uppercase tracking-widest mb-1">Close</div>
              <div className="text-sm font-bold text-white">
                ${visibleBars[visibleBars.length - 1]?.close?.toFixed(2) ?? '-'}
              </div>
            </div>
            <div className="bg-[#0a0a0a] border border-gray-900 p-4 rounded-xl">
              <div className="text-[9px] font-bold text-gray-600 uppercase tracking-widest mb-1">Avg Volume (21D)</div>
              <div className="text-sm font-bold text-gray-300">
                {avgDailyVolume21 !== null
                  ? avgDailyVolume21.toLocaleString(undefined, { maximumFractionDigits: 0 })
                  : '-'}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-6 mt-6 p-4 bg-[#0a0a0a] rounded-lg border border-gray-900">
        <div className="text-[10px] font-bold text-gray-600 uppercase tracking-widest mr-2 flex items-center">
          Chart Legend
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-[#CCFF00] rounded-sm" />
          <span className="text-[10px] font-bold text-gray-400 uppercase tracking-tighter">Bullish</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-[#ff5000] rounded-sm" />
          <span className="text-[10px] font-bold text-gray-400 uppercase tracking-tighter">Bearish</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-[rgba(204,255,0,0.5)] rounded-sm" />
          <span className="text-[10px] font-bold text-gray-400 uppercase tracking-tighter">Volume (Up)</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 bg-[rgba(255,80,0,0.5)] rounded-sm" />
          <span className="text-[10px] font-bold text-gray-400 uppercase tracking-tighter">Volume (Down)</span>
        </div>
      </div>
    </div>
  );
};

export default TradingViewChart;
