export const BILLING_USAGE_UPDATED_EVENT = 'openawa:billing-usage-updated'

export interface BillingUsageUpdatedDetail {
  callId?: string
  provider?: string
  model?: string
}

export function dispatchBillingUsageUpdated(detail?: BillingUsageUpdatedDetail): void {
  window.dispatchEvent(new CustomEvent(BILLING_USAGE_UPDATED_EVENT, { detail }))
}