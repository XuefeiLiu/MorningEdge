import React, { useState } from 'react';
import { useLocale } from '../i18n';
import LanguageSwitcher from './LanguageSwitcher';

interface LoginProps {
  onLogin: (username: string) => void;
}

const Login: React.FC<LoginProps> = ({ onLogin }) => {
  const { t } = useLocale();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (username.trim()) {
      onLogin(username);
    }
  };

  return (
    <div className="flex flex-col md:flex-row min-h-screen">
      {/* Visual Side */}
      <div className="hidden md:flex flex-1 bg-[#CCFF00] items-center justify-center p-12">
        <div className="max-w-md">
          <h1 className="text-black text-6xl font-bold mb-6 tracking-tight leading-none">
            {t('login.heroTitle')} <br />{t('login.heroTitleBreak')}
          </h1>
          <p className="text-black text-xl opacity-80 font-medium">
            {t('login.heroSub')}
          </p>
        </div>
      </div>

      {/* Form Side */}
      <div className="flex-1 flex items-center justify-center p-4 sm:p-8 bg-black relative">
        <LanguageSwitcher className="absolute top-4 right-4 sm:top-6 sm:right-6" />
        <div className="w-full max-w-sm">
          <div className="mb-12">
            <h2 className="text-3xl font-bold mb-2">{t('login.title')}</h2>
            <p className="text-gray-400">{t('login.tagline')}</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-gray-500 mb-2">
                {t('login.username')}
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full bg-transparent border-b border-gray-800 focus:border-[#CCFF00] outline-none py-2 transition-colors text-lg"
                placeholder={t('login.placeholderUsername')}
                required
              />
            </div>
            <div>
              <label className="block text-xs font-bold uppercase tracking-wider text-gray-500 mb-2">
                {t('login.password')}
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-transparent border-b border-gray-800 focus:border-[#CCFF00] outline-none py-2 transition-colors text-lg"
                placeholder={t('login.placeholderPassword')}
                required
              />
            </div>

            <button
              type="submit"
              className="w-full bg-[#CCFF00] text-black font-bold py-4 rounded-full hover:bg-[#b8e600] transition-all transform active:scale-[0.98] mt-4"
            >
              {t('login.submit')}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default Login;
