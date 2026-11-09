/** Shapes returned by the spendlens API (see backend/app/schemas.py and queries.py). */

export interface User {
  id: number;
  email: string;
  created_at: string;
}

export interface Account {
  id: number;
  bank: string;
  nickname: string;
  last4: string | null;
  currency: string;
  created_at: string;
}

export interface UploadResult {
  upload_id: number;
  account_id: number;
  inserted: number;
  skipped_duplicates: number;
  total_rows: number;
  categorized_by: { rule?: number; cache?: number; llm?: number };
}

export interface Summary {
  total_spent_cents: number;
  transaction_count: number;
  needs_review_count: number;
  first_date: string | null;
  last_date: string | null;
}

export interface CategoryTotal {
  category: string;
  total_cents: number;
  transaction_count: number;
  share: number;
}

export interface MonthTotal {
  month: string; // YYYY-MM
  total_cents: number;
  transaction_count: number;
}

export interface MerchantTotal {
  merchant: string;
  total_cents: number;
  transaction_count: number;
}
