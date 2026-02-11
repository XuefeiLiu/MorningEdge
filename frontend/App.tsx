import React, { useState } from 'react';
import { LocaleProvider } from './i18n';
import Login from './components/Login';
import Dashboard from './components/Dashboard';
import { UserState } from './types';

const App: React.FC = () => {
  const [user, setUser] = useState<UserState>({
    isLoggedIn: false,
    username: null,
  });

  const handleLogin = (username: string) => {
    setUser({ isLoggedIn: true, username });
  };

  const handleLogout = () => {
    setUser({ isLoggedIn: false, username: null });
  };

  return (
    <LocaleProvider>
      <div className="min-h-screen bg-black text-white selection:bg-[#CCFF00] selection:text-black">
        {!user.isLoggedIn ? (
          <Login onLogin={handleLogin} />
        ) : (
          <Dashboard username={user.username!} onLogout={handleLogout} />
        )}
      </div>
    </LocaleProvider>
  );
};

export default App;
