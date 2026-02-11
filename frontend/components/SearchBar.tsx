import React, { useState, useEffect, useRef } from 'react';
import { Search, Plus } from 'lucide-react';
import { useLocale } from '../i18n';

export interface StockInfo {
  ticker: string;
  name: string;
  exchange: string;
}

interface SearchBarProps {
  nasdaq100Stocks: StockInfo[];
  onAddStock: (stock: StockInfo) => void;
}

const SearchBar: React.FC<SearchBarProps> = ({ nasdaq100Stocks, onAddStock }) => {
  const { t } = useLocale();
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearchVisible, setIsSearchVisible] = useState(false);
  const [suggestions, setSuggestions] = useState<StockInfo[]>([]);
  const searchContainerRef = useRef<HTMLDivElement>(null);

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

  const handleSelect = (stock: StockInfo) => {
    onAddStock(stock);
    setSearchQuery('');
    setSuggestions([]);
    setIsSearchVisible(false);
  };

  const handleManualAdd = () => {
    if (!searchQuery.trim()) return;
    const ticker = searchQuery.toUpperCase().trim();
    const existing = nasdaq100Stocks.find(s => s.ticker === ticker);
    if (existing) {
      handleSelect(existing);
    } else {
      alert(`Stock ${ticker} is not in NASDAQ 100 list. Please select from the suggestions.`);
    }
  };

  return (
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
                  onClick={() => handleSelect(s)}
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
  );
};

export default SearchBar;
