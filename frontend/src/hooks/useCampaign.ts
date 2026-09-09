import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

export interface Campaign {
  campaign_id: string;
  name: string;
  status: string;
  created_at: string;
  stats?: Record<string, number>;
}

export function useCampaigns() {
  return useQuery<{ success: boolean; data: Campaign[] }>({
    queryKey: ['campaigns'],
    queryFn: () => api.get('/api/campaigns'),
    refetchInterval: 3000,
    retry: false,
  });
}

export function useCampaign(id: string) {
  return useQuery<{ success: boolean; data: Campaign }>({
    queryKey: ['campaign', id],
    queryFn: () => api.get(`/api/campaigns/${id}`),
    refetchInterval: 3000,
    enabled: !!id,
    retry: false,
  });
}

export function useCloneCampaign() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      api.post(`/api/campaigns/${id}/clone`, { name }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['campaigns'] }),
  });
}

export function useUpdateCampaign() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      api.put(`/api/campaigns/${id}`, { name }),
    onSuccess: (_data, { id }) => {
      queryClient.invalidateQueries({ queryKey: ['campaigns'] });
      queryClient.invalidateQueries({ queryKey: ['campaign', id] });
    },
  });
}
