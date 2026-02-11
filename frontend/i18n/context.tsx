import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { en } from './locales/en';
import { zh } from './locales/zh';

const STORAGE_KEY = 'locale';

export type Locale = 'en' | 'zh';

const messages: Record<Locale, Record<string, unknown>> = { en, zh };

function getInitialLocale(): Locale {
  if (typeof window === 'undefined') return 'en';
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'zh' || stored === 'en') return stored;
  return 'en';
}

function getNested(obj: Record<string, unknown>, path: string): string | undefined {
  const parts = path.split('.');
  let current: unknown = obj;
  for (const part of parts) {
    if (current == null || typeof current !== 'object') return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return typeof current === 'string' ? current : undefined;
}

type TFn = (key: string, params?: Record<string, string | number>) => string;

function createT(locale: Locale): TFn {
  const fallback = en as Record<string, unknown>;
  const current = messages[locale] as Record<string, unknown>;
  return (key: string, params?: Record<string, string | number>): string => {
    let s = getNested(current, key) ?? getNested(fallback, key);
    if (s === undefined) return key;
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        s = s.replace(new RegExp(`\\{\\{${k}\\}\\}`, 'g'), String(v));
      });
    }
    return s;
  };
}

interface LocaleContextValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: TFn;
}

const LocaleContext = createContext<LocaleContextValue | null>(null);

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => getInitialLocale());

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    if (typeof window !== 'undefined') localStorage.setItem(STORAGE_KEY, l);
  }, []);

  const value = useMemo<LocaleContextValue>(
    () => ({
      locale,
      setLocale,
      t: createT(locale),
    }),
    [locale, setLocale]
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext);
  if (!ctx) throw new Error('useLocale must be used within LocaleProvider');
  return ctx;
}
