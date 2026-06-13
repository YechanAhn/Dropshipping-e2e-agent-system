export interface ProductOut {
  id: number;
  ali_product_id: string;
  naver_product_id: string | null;
  product_name_en: string | null;
  product_name_ko: string | null;
  category_ali: string | null;
  category_naver: string | null;
  price_ali: number | null; // AliExpress sale price, in KRW (target_currency=KRW)
  price_ali_krw: number | null; // mirror of price_ali (already KRW)
  price_naver: number | null; // our SmartStore sale price (KRW)
  // 최저가 노출 추적
  naver_catalog_lowest: number | null; // 가격비교 대표(catalog) 최저가 = 배지 가격
  naver_price_min_market: number | null; // 검색결과 전체 최저가 (단독 포함)
  is_price_lowest: boolean; // 현재 최저가(배지) 보유 여부
  price_floor: number | null; // 마진 하한 가격
  pricing_strategy: string | null; // catalog_match | standalone
  last_repriced_at: string | null;
  price_gap: number | null; // price_naver - naver_catalog_lowest (양수면 더 비쌈)
  badge_at_risk: boolean; // 최저가보다 비싸 배지 미확보 → 노출 위험
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
  auto_reprice: boolean;
}

export interface Settings {
  scoring_weights: ScoringWeights;
  automation_flags: AutomationFlags;
}

export interface HealthStatus {
  status: string;
}
