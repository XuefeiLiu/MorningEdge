import React from 'react';
import { DarkDatePicker } from './DarkDatePicker';
import { useLocale } from '../i18n/context';

interface NewsFilterPanelProps {
  selectedTimeframe: string;
  customRange: { start: string; end: string };
  onTimeframeChange: (tf: string) => void;
  onCustomRangeChange: (range: { start: string; end: string }) => void;
}

const TIMEFRAMES = ['1D', '2D', '3D', '1W'] as const;

const NewsFilterPanel: React.FC<NewsFilterPanelProps> = ({
  selectedTimeframe,
  customRange,
  onTimeframeChange,
  onCustomRangeChange,
}) => {
  const { t } = useLocale();

  return (
    <div className="flex flex-wrap items-center gap-4 mb-6">
      <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">{t('stockDetail.date')}</span>
      <div className="flex flex-wrap gap-2">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            onClick={() => { onTimeframeChange(tf); onCustomRangeChange({ start: '', end: '' }); }}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-all ${!customRange.start && !customRange.end && selectedTimeframe === tf ? 'bg-[#CCFF00] text-black border-[#CCFF00]' : 'border-gray-700 text-gray-400 hover:text-white hover:border-gray-600'}`}
          >
            {tf}
          </button>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <DarkDatePicker
          value={customRange.start || ''}
          onChange={(v) => {
            onCustomRangeChange({
              start: v || '',
              end: customRange.end || '',
            });
          }}
          placeholder="Start date"
          aria-label="Select start date"
        />
        <span className="text-xs text-gray-500">to</span>
        <DarkDatePicker
          value={customRange.end || ''}
          onChange={(v) => {
            onCustomRangeChange({
              start: customRange.start || '',
              end: v || '',
            });
          }}
          placeholder="End date"
          aria-label="Select end date"
        />
        {(customRange.start || customRange.end) && (
          <button
            onClick={() => onCustomRangeChange({ start: '', end: '' })}
            className="px-2 py-1 text-xs text-gray-500 hover:text-white"
            aria-label="Clear date range"
          >
            Clear
          </button>
        )}
      </div>
    </div>
  );
};

export default NewsFilterPanel;
