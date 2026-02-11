
export interface Stock {
  symbol: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  extendedChange?: number | null;
  extendedChangePercent?: number | null;
}

export type ViewType = 'Portfolio' | 'Watchlist';

export interface UserState {
  isLoggedIn: boolean;
  username: string | null;
}

export type NewsCategory = 'Stock' | 'Industry' | 'Macro' | 'Sentiment';
export type SentimentType = 'Bullish' | 'Bearish' | 'Neutral';

export interface NewsItem {
  id: string;
  symbol: string;
  timestamp: string; // ISO format for easy sorting/filtering
  category: NewsCategory;
  source: string;
  title: string;
  summary: string;
  sentiment: SentimentType;
  url?: string; // Optional URL for news article
  primaryTopic?: string; // For Macro news only
  relatedTickers?: string[]; // For Macro news only
}
