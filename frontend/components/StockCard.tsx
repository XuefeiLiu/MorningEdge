import React from 'react';
import { Stock } from '../types';
import { X, TrendingUp, TrendingDown } from 'lucide-react';
import { useLocale } from '../i18n/context';
import { getPredictionStyle } from '../constants';

interface StockCardProps {
  stock: Stock;
  onRemove: () => void;
  onClick: () => void;
  storylineTitle?: string | null;
  storylineType?: string | null;
}

const StockCard: React.FC<StockCardProps> = ({ stock, onRemove, onClick, storylineTitle, storylineType }) => {
  const { t } = useLocale();
  const isPositive = stock.change >= 0;
  const accentColor = isPositive ? '#CCFF00' : '#ff5000';

  // Extended hours return info (show whenever backend provides it, even if 0%)
  const hasExtended = stock.extendedChangePercent != null;
  const extVal = stock.extendedChangePercent ?? 0;
  const extIsPositive = extVal >= 0;
  const extColor = extVal === 0 ? '#888888' : (extIsPositive ? '#CCFF00' : '#ff5000');

  return (
    <div 
      onClick={onClick}
      className="group relative bg-[#0a0a0a] border border-gray-900 hover:border-gray-700 p-5 rounded-xl transition-all duration-300 cursor-pointer hover:shadow-[0_0_20px_rgba(0,0,0,0.5)]"
    >
      {/* Delete Button - Visible on hover */}
      <button 
        onClick={(e) => { e.stopPropagation(); onRemove(); }}
        className="absolute top-3 right-3 p-1.5 rounded-full bg-gray-900 text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity hover:text-white z-10"
      >
        <X size={14} />
      </button>

      <div className="flex justify-between items-start mb-4">
        <div>
          <h3 className="text-xl font-bold tracking-tight group-hover:text-[#CCFF00] transition-colors">{stock.symbol}</h3>
          <p className="text-xs text-gray-500 font-medium truncate max-w-[120px]">{stock.name}</p>
        </div>
        <div className="text-right">
          <p className="text-lg font-bold">${stock.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
          <div className={`flex items-center justify-end text-sm font-bold`} style={{ color: accentColor }}>
            {isPositive ? <TrendingUp size={14} className="mr-1" /> : <TrendingDown size={14} className="mr-1" />}
            {isPositive ? '+' : ''}{stock.changePercent.toFixed(2)}%
          </div>
          {hasExtended && (
            <div className="flex items-center justify-end text-[10px] font-semibold mt-0.5" style={{ color: extColor, opacity: 0.8 }}>
              {extIsPositive ? '+' : ''}{extVal.toFixed(2)}%
              <span className="ml-1 text-gray-500 font-normal">AH</span>
            </div>
          )}
        </div>
      </div>

      {/* Mini Visualizer Placeholder */}
      <div className="h-12 w-full mt-2 overflow-hidden flex items-end">
        <div className="flex items-end gap-[2px] w-full h-full opacity-40 group-hover:opacity-100 transition-opacity">
          {Array.from({ length: 12 }).map((_, i) => {
            const height = Math.random() * 80 + 20;
            return (
              <div 
                key={i} 
                className="flex-1 rounded-t-sm" 
                style={{ 
                  height: `${height}%`, 
                  backgroundColor: accentColor,
                  opacity: (i + 1) / 12 
                }} 
              />
            );
          })}
        </div>
      </div>

      {/* Storyline title or prediction */}
      <div className="mt-3 min-h-[2.5rem]">
        {storylineTitle ? (
          <div className="flex items-start gap-2">
            <p
              className="text-xs font-bold line-clamp-2 leading-tight flex-1"
              style={{ color: getPredictionStyle(storylineTitle).color }}
            >
              {(storylineTitle.includes('↑') || storylineTitle.includes('↓') || storylineTitle === 'Neutral')
                ? `${t('stockCard.marketOpenPrediction')} ${storylineTitle}`
                : storylineTitle}
            </p>
            {storylineType && (
              <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider flex-shrink-0 ${
                storylineType === 'filing'
                  ? 'bg-blue-900/30 text-blue-400 border border-blue-700/50'
                  : storylineType === 'OVERNIGHT'
                    ? 'bg-amber-900/30 text-amber-400 border border-amber-700/50'
                    : 'bg-gray-800 text-gray-400 border border-gray-700'
              }`}>
                {storylineType}
              </span>
            )}
          </div>
        ) : null}
      </div>
      
      <div className="mt-4 pt-4 border-t border-gray-900">
        <div className="flex items-center gap-2 text-[10px] text-gray-600 font-bold uppercase tracking-widest">
          <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: accentColor }} />
          {t('stockCard.analyzeNarrative')}
        </div>
      </div>
    </div>
  );
};

export default StockCard;
