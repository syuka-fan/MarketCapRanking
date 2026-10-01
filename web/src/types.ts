export interface Price { ticker: string; close: number; quote_date?: string }
export interface Point { rank: number; market_cap_usd: number; prices: Price[] }
export interface Instrument { id: string; name: string; tickers: string[]; history_file: string }
export interface Row extends Point {
  instrument_id: string;
  company_name: string;
  ticker: string;
  security_type: string;
  shares_outstanding: string;
  shares_source: string;
  rank_change: number | null;
  change_state: 'known' | 'new' | 'baseline' | 'gap';
}
export interface Index {
  schema_version: number;
  dates: string[];
  closed_dates?: string[];
  provisional_date?: string | null;
  provisional_at?: string | null;
  axis_dates: string[];
  instruments: Instrument[];
  is_demo: boolean;
  source: string | null;
  coverage?: {
    screened_tickers?: number;
    directory_eligible: number;
    quoted_eligible: number;
    rankable_tickers?: number;
    unquoted_tickers: string[];
    stale_quote_tickers?: string[];
    excluded_quotes?: { ticker: string; reason: string }[];
    by_type?: Record<string, { eligible: number; ranked: number }>;
  } | null;
  method: string;
  scope: string;
  status: {
    state: string;
    last_success_at: string | null;
    attempted_at?: string;
    expected_trade_date?: string;
    latest_trade_date: string | null;
  };
}
