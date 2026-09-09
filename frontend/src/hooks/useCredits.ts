import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

export interface CreditBalance {
  balance: number;
  tenant_id: string;
}

export interface CreditPricing {
  tenant_id: string;
  price_per_credit: number;
}

export interface LedgerEntry {
  id: number;
  transaction_type: 'purchase' | 'reservation' | 'deduction' | 'release' | 'adjustment';
  amount: number;
  call_sid: string | null;
  campaign_id: string | null;
  description: string | null;
  created_at: string;
}

export interface LedgerResponse {
  entries: LedgerEntry[];
  total: number;
  page: number;
  page_size: number;
}

export interface PurchaseRequest {
  amount: number;
  description?: string;
  idempotency_key?: string;
}

export interface PurchaseResponse {
  balance: number;
  transaction_id: string;
}

export function useCredits() {
  const balance = useQuery<CreditBalance>({
    queryKey: ['credits', 'balance'],
    queryFn: () => api.get<CreditBalance>('/api/credits/balance'),
    refetchInterval: 10000,
  });

  const ledger = useQuery<LedgerResponse>({
    queryKey: ['credits', 'ledger'],
    queryFn: () => api.get<LedgerResponse>('/api/credits/ledger?page=1&page_size=50'),
    refetchInterval: 10000,
  });

  const pricing = useQuery<CreditPricing>({
    queryKey: ['credits', 'pricing'],
    queryFn: () => api.get<CreditPricing>('/api/credits/pricing'),
    refetchInterval: 60000,
  });

  return { balance, ledger, pricing };
}

export function usePurchaseCredits() {
  const queryClient = useQueryClient();
  return useMutation<PurchaseResponse, Error, PurchaseRequest>({
    mutationFn: (body: PurchaseRequest) =>
      api.post<PurchaseResponse>('/api/credits/purchase', body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credits'] });
    },
  });
}
