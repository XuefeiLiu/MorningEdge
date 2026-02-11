import React from 'react';
import { useLocale } from '../i18n';

/** Compact EN | 中文 switcher. Use in Login and Dashboard header. */
const LanguageSwitcher: React.FC<{ className?: string }> = ({ className = '' }) => {
  const { locale, setLocale } = useLocale();
  return (
    <div className={`flex items-center gap-1 text-xs font-bold uppercase tracking-wider ${className}`}>
      <button
        type="button"
        onClick={() => setLocale('en')}
        className={`px-2 py-1 rounded transition-colors ${locale === 'en' ? 'text-[#CCFF00]' : 'text-gray-500 hover:text-white'}`}
      >
        EN
      </button>
      <span className="text-gray-600">|</span>
      <button
        type="button"
        onClick={() => setLocale('zh')}
        className={`px-2 py-1 rounded transition-colors ${locale === 'zh' ? 'text-[#CCFF00]' : 'text-gray-500 hover:text-white'}`}
      >
        中文
      </button>
    </div>
  );
};

export default LanguageSwitcher;
