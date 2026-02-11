import React from 'react';
import { Stock } from '../types';
import { useLocale } from '../i18n';
import { getPredictionStyle } from '../constants';

interface StorylineRow {
  ticker: string;
  title: string;
  last_updated_at: string | null;
  prediction: string | null;
}

interface StorylineTableProps {
  rows: StorylineRow[];
  activeList: Stock[];
  onSelectStock: (stock: Stock) => void;
}

const StorylineTable: React.FC<StorylineTableProps> = ({ rows, activeList, onSelectStock }) => {
  const { t } = useLocale();

  if (rows.length === 0) return null;

  return (
    <div className="mt-10 border border-gray-800 rounded-xl bg-[#0a0a0a] overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800">
        <h3 className="text-sm font-bold text-gray-300 uppercase tracking-wider">{t('narrative.highImpactOvernight')}</h3>
        <p className="text-xs text-gray-500 mt-0.5">{t('narrative.expectedMoveAtOpen')}</p>
      </div>
      <div className="divide-y divide-gray-800">
        {rows.map((row, i) => {
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
            : '\u2014';
          return (
            <button
              key={`${row.ticker}-${i}`}
              type="button"
              onClick={() => stock && onSelectStock(stock)}
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
                  <span className="mx-1.5">&middot;</span>
                  {dateStr}
                </p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default StorylineTable;
