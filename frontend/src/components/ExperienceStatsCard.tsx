import { ReactNode } from 'react'

interface Props {
  title: string
  value: string | number
  icon: ReactNode
}

function ExperienceStatsCard({ title, value, icon }: Props) {
  return (
    <div className="stats-card">
      <div className="stats-icon-wrapper">{icon}</div>
      <div className="stats-info">
        <div className="stats-value">{value}</div>
        <div className="stats-title">{title}</div>
      </div>
    </div>
  )
}

export default ExperienceStatsCard
