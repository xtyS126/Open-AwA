import { describe, expectTypeOf, it } from 'vitest'
import type { BehaviorStats, BillingStats, Plugin } from '@/features/dashboard/dashboard'

describe('dashboard contracts', () => {
  it('requires complete behavior statistics', () => {
    expectTypeOf<BehaviorStats>().toMatchTypeOf<{
      total_interactions: number
      total_tools_used: number
      average_response_time: number
    }>()
  })

  it('keeps billing trend items numeric', () => {
    expectTypeOf<BillingStats['trend'][number]['cost']>().toEqualTypeOf<number>()
  })

  it('preserves protected plugin flags in the dashboard contract', () => {
    expectTypeOf<Plugin['is_uninstallable']>().toEqualTypeOf<boolean | null | undefined>()
  })
})
