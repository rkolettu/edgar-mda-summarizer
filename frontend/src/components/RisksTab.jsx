import { CalendarCheck, ChevronDown, CircleDashed, Plus, TrendingUp } from 'lucide-react'
import { useState } from 'react'
import { TypeTag } from './ChangesSection'
import { Passage } from './FilingChangesTab'
import { AiLabel, Badge, Card, InsightsNotice, QuotedList, SectionHeader, SynthPoint } from './Insights'
import { Evidence } from './Verification'

const TREND = {
  new: { label: 'New', icon: Plus, tone: 'accent' },
  heightened: { label: 'Heightened', icon: TrendingUp, tone: 'plain' },
  ongoing: { label: 'Ongoing', icon: null, tone: 'quiet' },
}

function RiskBadges({ trend, extracted }) {
  const t = TREND[trend] ?? TREND.ongoing
  return (
    <>
      <Badge tone={t.tone} icon={t.icon}>{t.label}</Badge>
      {extracted && (
        extracted.realized
          ? <Badge icon={CalendarCheck}>Has happened</Badge>
          : <Badge tone="quiet" icon={CircleDashed}>Could happen</Badge>
      )}
      {extracted?.category && <span className="text-[11px] text-muted">{extracted.category}</span>}
    </>
  )
}

function Ranked({ risks }) {
  if (!risks?.length) return null
  return (
    <Card title="Risks that matter most now" className="mb-5">
      <ol className="divide-y divide-line">
        {risks.map((risk, i) => (
          <li key={i} className="px-5 py-5 sm:px-6">
            <SynthPoint item={risk} badges={<RiskBadges trend={risk.trend} extracted={risk.extracted} />} />
            {risk.extracted && <Evidence item={risk.extracted} where={`the ${risk.extracted.source.fiscal_label} ${risk.extracted.source.form}`} />}
          </li>
        ))}
      </ol>
    </Card>
  )
}

const VISIBLE_CHANGES = 8

// Risk factor language the latest filing added or changed, found by comparing the text in code.
function WordingChanges({ changes }) {
  const [expanded, setExpanded] = useState(false)
  const all = (changes?.items ?? []).filter((i) => i.category === 'risk_factors')
  const items = expanded ? all : all.slice(0, VISIBLE_CHANGES)
  const base = all[0]?.base_filing
  return (
    <Card
      title="Risk factor wording that changed"
      aside={base && <span className="text-xs text-muted">vs. the {base.fiscal_label} {base.form}</span>}
      className="mb-5"
    >
      {all.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted sm:px-6">
          No new or reworded risk factor language was found in the latest filing, or its risk factors could not be read.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {items.map((item, i) => (
            <li key={i} className="px-5 py-4 sm:px-6">
              <div className="flex flex-wrap items-center gap-2">
                <TypeTag type={item.change_type} />
                {item.triggers?.length > 0 && <span className="text-[11px] text-muted">mentions {item.triggers.slice(0, 3).join(', ')}</span>}
                {item.first_disclosed && <span className="text-[11px] text-muted">first disclosed in {item.first_disclosed}</span>}
                <span className="ml-auto font-mono text-[11px] text-muted">{item.score.toFixed(2)}</span>
              </div>
              <Passage text={item.text} />
              {item.base_text && <Passage text={item.base_text} label="Previously" />}
            </li>
          ))}
        </ul>
      )}
      {all.length > VISIBLE_CHANGES && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          className="flex w-full items-center justify-center gap-1.5 border-t border-line px-5 py-3 text-xs font-medium text-accent hover:bg-panel-2 hover:text-accent-hover"
        >
          <ChevronDown size={13} aria-hidden className={expanded ? 'rotate-180' : ''} />
          {expanded ? 'Show fewer' : `Show all ${all.length} changes`}
        </button>
      )}
    </Card>
  )
}

export default function RisksTab({ research, request }) {
  const { insights, changes } = research
  const ranked = insights?.risks?.ranked ?? []
  const shown = new Set(ranked.map((r) => r.extracted?.headline).filter(Boolean))
  const others = (insights?.risks?.extracted ?? []).filter((r) => !shown.has(r.headline) && r.company_specific !== false)
  return (
    <div>
      <SectionHeader eyebrow="Risk factors" title="Risks" aside={<AiLabel insights={insights} />}>
        New and heightened risks first. The wording changes below are found by comparing the filings in code; the ranking and summaries are
        written by AI from those changes and quoted risk factor text, and state whether a risk has already happened or could happen.
      </SectionHeader>
      <InsightsNotice insights={insights} request={request} />
      <Ranked risks={ranked} />
      <WordingChanges changes={changes} />
      {others.length > 0 && (
        <Card title="Other company-specific risks in the filings">
          <QuotedList items={others} empty="" badges={(item) => <RiskBadges trend={item.trend} extracted={item} />} />
        </Card>
      )}
    </div>
  )
}
