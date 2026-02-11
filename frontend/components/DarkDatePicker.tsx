import React, { useState, useRef, useEffect } from 'react';
import { Calendar, ChevronLeft, ChevronRight } from 'lucide-react';

interface DarkDatePickerProps {
  value: string; // YYYY-MM-DD
  onChange: (value: string) => void;
  className?: string;
  placeholder?: string;
  id?: string;
  'aria-label'?: string;
}

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const DOW = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

function toLocalDateString(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function formatDisplay(iso: string): string {
  if (!iso) return '';
  const [y, m, d] = iso.split('-');
  return `${m}/${d}/${y}`;
}

export function DarkDatePicker({ value, onChange, className = '', placeholder = 'Select date', id, 'aria-label': ariaLabel }: DarkDatePickerProps) {
  const [open, setOpen] = useState(false);
  const [viewDate, setViewDate] = useState(() => {
    if (value) {
      const [y, m] = value.split('-').map(Number);
      return new Date(y, m - 1, 1);
    }
    return new Date();
  });
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    if (value) {
      const [y, m] = value.split('-').map(Number);
      setViewDate(new Date(y, m - 1, 1));
    } else {
      setViewDate(new Date());
    }
  }, [open, value]);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  const viewYear = viewDate.getFullYear();
  const viewMonth = viewDate.getMonth();
  const today = toLocalDateString(new Date());

  const first = new Date(viewYear, viewMonth, 1);
  const last = new Date(viewYear, viewMonth + 1, 0);
  const startPad = first.getDay();
  const daysInMonth = last.getDate();
  const cells: (number | null)[] = [];
  for (let i = 0; i < startPad; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  const remainder = 42 - cells.length;
  for (let i = 0; i < remainder; i++) cells.push(null);

  const prevMonth = () => setViewDate((d) => new Date(d.getFullYear(), d.getMonth() - 1, 1));
  const nextMonth = () => setViewDate((d) => new Date(d.getFullYear(), d.getMonth() + 1, 1));

  const selectDay = (day: number | null) => {
    if (day == null) return;
    const next = new Date(viewYear, viewMonth, day);
    onChange(toLocalDateString(next));
    setOpen(false);
  };

  const handleClear = () => {
    onChange('');
    setOpen(false);
  };

  const handleToday = () => {
    onChange(today);
    setOpen(false);
  };

  return (
    <div ref={containerRef} className="relative inline-block">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className={`p-1.5 rounded-lg text-gray-500 hover:text-white hover:bg-gray-800 transition-colors ${className}`}
          aria-label={ariaLabel ?? 'Open date picker'}
        >
          <Calendar size={14} />
        </button>
        <button
          type="button"
          onClick={() => setOpen(true)}
          id={id}
          aria-label={ariaLabel}
          className={`bg-black border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-gray-200 outline-none focus:border-[#CCFF00] transition-colors min-w-[7rem] text-left ${className}`}
        >
          {value ? formatDisplay(value) : placeholder}
        </button>
      </div>
      {open && (
        <div className="absolute left-0 top-full mt-1 z-50 rounded-lg border border-gray-700 bg-gray-900 shadow-xl p-3 min-w-[240px]">
          <div className="flex items-center justify-between mb-3">
            <button type="button" onClick={prevMonth} className="p-1 rounded text-gray-400 hover:text-white hover:bg-gray-800" aria-label="Previous month">
              <ChevronLeft size={18} />
            </button>
            <span className="text-sm font-semibold text-gray-100">
              {MONTHS[viewMonth]} {viewYear}
            </span>
            <button type="button" onClick={nextMonth} className="p-1 rounded text-gray-400 hover:text-white hover:bg-gray-800" aria-label="Next month">
              <ChevronRight size={18} />
            </button>
          </div>
          <div className="grid grid-cols-7 gap-0.5 mb-2">
            {DOW.map((d) => (
              <div key={d} className="text-center text-[10px] font-bold text-gray-500 py-1">
                {d}
              </div>
            ))}
            {cells.map((day, i) => {
              if (day === null) {
                return <div key={`e-${i}`} className="p-1" />;
              }
              const dateStr = toLocalDateString(new Date(viewYear, viewMonth, day));
              const isSelected = value === dateStr;
              const isToday = dateStr === today;
              return (
                <button
                  key={day}
                  type="button"
                  onClick={() => selectDay(day)}
                  className={`p-1.5 rounded text-xs font-medium transition-colors ${
                    isSelected ? 'bg-[#CCFF00] text-black' : isToday ? 'border border-gray-500 text-gray-200' : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                  }`}
                >
                  {day}
                </button>
              );
            })}
          </div>
          <div className="flex justify-end gap-2 pt-2 border-t border-gray-800">
            <button type="button" onClick={handleClear} className="text-xs text-[#3b82f6] hover:underline">
              Clear
            </button>
            <button type="button" onClick={handleToday} className="text-xs text-[#3b82f6] hover:underline">
              Today
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
