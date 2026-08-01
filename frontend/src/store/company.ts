import { create } from 'zustand'

export interface CompanyProfileState {
  bound: boolean
  id: string | null
  legalName: string
  shortName: string
  brandName: string
  description: string
  setProfile: (profile: {
    bound: boolean
    id?: string | null
    legal_name?: string
    short_name?: string
    brand_name?: string
    description?: string
  }) => void
  reset: () => void
}

const defaults = {
  bound: false,
  id: null,
  legalName: '',
  shortName: 'OpenTrace',
  brandName: 'OpenTrace',
  description: '',
}

export const useCompanyStore = create<CompanyProfileState>((set) => ({
  ...defaults,
  setProfile: (profile) => set({
    bound: Boolean(profile.bound),
    id: profile.id ?? null,
    legalName: profile.legal_name ?? '',
    shortName: profile.short_name?.trim() || 'OpenTrace',
    brandName: profile.brand_name?.trim() || profile.short_name?.trim() || 'OpenTrace',
    description: profile.description ?? '',
  }),
  reset: () => set(defaults),
}))

export function getCompanyBrandName(): string {
  return useCompanyStore.getState().brandName || 'OpenTrace'
}
