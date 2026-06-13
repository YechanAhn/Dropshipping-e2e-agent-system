export interface ProductOut {
  id: number;
  ali_product_id: string;
  naver_product_id: string | null;
  product_name_en: string | null;
  product_name_ko: string | null;
  category_ali: string | null;
  category_naver: string | null;
  price_ali: number | null; // AliExpress sale price, in USD
  price_ali_krw: number | null; // AliExpress price converted to KRW (server-computed)
  price_naver: number | null;
  margin_rate: number | null;
  priority_score: number | null;
  risk_score: number | null;
  ops_cost_score: number | null;
  demand_score: number | null;
  status: string;
}

export interface OrderOut {
  id: number;
  naver_order_id: string;
  ali_order_id: string | null;
  product_id: number;
  quantity: number;
  total_price: number;
  status: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface TrendingKeyword {
  keyword?: string;
  search_volume?: number;
  category?: string;
  [key: string]: unknown;
}

export interface AnalyticsSummary {
  revenue_summary: Record<string, unknown>;
  order_counts: Record<string, number>;
  top_trending_keywords: TrendingKeyword[];
}

export interface ScoringWeights {
  margin: number;
  demand: number;
  risk: number;
  ops_cost: number;
}

export interface AutomationFlags {
  auto_approve: boolean;
  auto_register: boolean;
  auto_order: boolean;
}

export interface Settings {
  scoring_weights: ScoringWeights;
  automation_flags: AutomationFlags;
}

export interface HealthStatus {
  status: string;
}
