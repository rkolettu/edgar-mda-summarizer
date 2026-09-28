export function usefulBreakdowns(breakdowns = []) {
  return breakdowns.filter((breakdown) => {
    const view = breakdown.annual ?? breakdown.quarterly
    const revenueItems = (view?.items ?? []).filter((item) => item.metric === 'revenue')
    // A sole reportable segment equal to the whole company adds no business-mix information. Product and geography
    // disclosures remain useful even when each happens to contain only one tagged item.
    return breakdown.family !== 'segment' || revenueItems.length > 1
  })
}
