/**
 * Cron表达式生成器组件。
 * 提供可视化界面让用户设置定时规则，支持预设模板和自定义配置。
 */
import { useState, useMemo, useCallback } from 'react'
import { Clock, Calendar, Repeat, ChevronRight } from 'lucide-react'
import styles from './CronExpressionBuilder.module.css'

interface CronConfig {
  cron_expression: string
  is_daily: boolean
  weekdays: string
  daily_time: string
}

interface Props {
  onChange: (config: CronConfig) => void
  initialIsDaily?: boolean
  initialWeekdays?: string
  initialDailyTime?: string
}

type PresetType = 'every_minute' | 'every_hour' | 'every_day' | 'every_week' | 'every_month' | 'custom'

const PRESETS: { type: PresetType; label: string; description: string; icon: typeof Clock }[] = [
  { type: 'every_minute', label: '每分钟', description: '每分钟执行一次', icon: Clock },
  { type: 'every_hour', label: '每小时', description: '每小时整点执行', icon: Clock },
  { type: 'every_day', label: '每天', description: '每天固定时间执行', icon: Calendar },
  { type: 'every_week', label: '每周', description: '每周指定日期执行', icon: Calendar },
  { type: 'every_month', label: '每月', description: '每月指定日期执行', icon: Repeat },
  { type: 'custom', label: '自定义', description: '手动设置Cron表达式', icon: Repeat },
]

const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

function cronToHuman(expression: string): string {
  if (!expression || !expression.trim()) return ''
  const parts = expression.trim().split(/\s+/)
  if (parts.length !== 5) return expression

  const [minute, hour, , , dayOfWeek] = parts
  const h = parseInt(hour, 10)
  const m = parseInt(minute, 10)
  const timeStr = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`

  if (minute === '*' && hour === '*' && dayOfWeek === '*') return '每分钟'
  if (minute !== '*' && hour === '*' && dayOfWeek === '*') return `每小时第${minute}分`
  if (dayOfWeek === '*') return `每天 ${timeStr}`
  if (dayOfWeek.includes(',')) {
    const days = dayOfWeek.split(',').map((d) => WEEKDAY_LABELS[parseInt(d, 10)] || d)
    return `每${days.join('、')} ${timeStr}`
  }
  if (!isNaN(parseInt(dayOfWeek))) {
    return `每${WEEKDAY_LABELS[parseInt(dayOfWeek, 10)] || dayOfWeek} ${timeStr}`
  }

  return `${minute} ${hour} ${parts[2]} ${parts[3]} ${dayOfWeek}`
}

function buildCronFromPreset(preset: PresetType, dailyTime: string, weekdays: Set<number>): string {
  const [h, m] = dailyTime.split(':').map(Number)
  switch (preset) {
    case 'every_minute':
      return '* * * * *'
    case 'every_hour':
      return '0 * * * *'
    case 'every_day':
      return `${m} ${h} * * *`
    case 'every_week': {
      const days = Array.from(weekdays).sort().join(',')
      return `${m} ${h} * * ${days || '*'}`
    }
    case 'every_month':
      return `${m} ${h} 1 * *`
    default:
      return `${m} ${h} * * ${Array.from(weekdays).sort().join(',') || '*'}`
  }
}

export default function CronExpressionBuilder({
  onChange,
  initialIsDaily,
  initialWeekdays,
  initialDailyTime,
}: Props) {
  const [isDaily, setIsDaily] = useState(initialIsDaily ?? false)
  const [dailyTime, setDailyTime] = useState(initialDailyTime || '09:00')
  const [selectedWeekdays, setSelectedWeekdays] = useState<Set<number>>(() => {
    if (initialWeekdays) {
      return new Set(initialWeekdays.split(',').map(Number).filter((n) => !isNaN(n)))
    }
    return new Set([0, 1, 2, 3, 4, 5, 6])
  })
  const [selectedPreset, setSelectedPreset] = useState<PresetType>(
    isDaily ? 'every_day' : 'custom'
  )

  const cronExpression = useMemo(() => {
    if (!isDaily) return ''
    return buildCronFromPreset(selectedPreset, dailyTime, selectedWeekdays)
  }, [isDaily, selectedPreset, dailyTime, selectedWeekdays])

  const humanDescription = useMemo(() => cronToHuman(cronExpression), [cronExpression])

  const emitChange = useCallback(
    (isd: boolean, preset: PresetType, time: string, weekdays: Set<number>) => {
      const expr = isd ? buildCronFromPreset(preset, time, weekdays) : ''
      onChange({
        cron_expression: expr,
        is_daily: isd,
        weekdays: Array.from(weekdays).sort().join(','),
        daily_time: time,
      })
    },
    [onChange]
  )

  const handleIsDailyToggle = (checked: boolean) => {
    setIsDaily(checked)
    if (checked) {
      setSelectedPreset('every_day')
    } else {
      setSelectedPreset('custom')
    }
    emitChange(checked, checked ? 'every_day' : 'custom', dailyTime, selectedWeekdays)
  }

  const handlePresetSelect = (preset: PresetType) => {
    setSelectedPreset(preset)
    emitChange(isDaily, preset, dailyTime, selectedWeekdays)
  }

  const handleTimeChange = (time: string) => {
    setDailyTime(time)
    emitChange(isDaily, selectedPreset, time, selectedWeekdays)
  }

  const toggleWeekday = (day: number) => {
    setSelectedWeekdays((prev) => {
      const next = new Set(prev)
      if (next.has(day)) {
        if (next.size > 1) next.delete(day)
      } else {
        next.add(day)
      }
      emitChange(isDaily, selectedPreset, dailyTime, next)
      return next
    })
  }

  return (
    <div className={styles['container']}>
      {/* 每日执行开关 */}
      <label className={styles['toggle']}>
        <input
          type="checkbox"
          checked={isDaily}
          onChange={(e) => handleIsDailyToggle(e.target.checked)}
        />
        <span>启用重复执行</span>
      </label>

      {isDaily && (
        <div className={styles['config']}>
          {/* 预设模板 */}
          <div className={styles['section']}>
            <span className={styles['section-label']}>执行频率</span>
            <div className={styles['preset-grid']}>
              {PRESETS.map((preset) => {
                const Icon = preset.icon
                const isActive = selectedPreset === preset.type
                return (
                  <button
                    key={preset.type}
                    type="button"
                    className={`${styles['preset-card']} ${isActive ? styles['active'] : ''}`}
                    onClick={() => handlePresetSelect(preset.type)}
                  >
                    <Icon size={18} />
                    <span className={styles['preset-label']}>{preset.label}</span>
                    <span className={styles['preset-desc']}>{preset.description}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* 时间选择器 */}
          {(selectedPreset === 'every_day' ||
            selectedPreset === 'every_week' ||
            selectedPreset === 'every_month' ||
            selectedPreset === 'custom') && (
            <div className={styles['section']}>
              <span className={styles['section-label']}>执行时间</span>
              <input
                type="time"
                value={dailyTime}
                onChange={(e) => handleTimeChange(e.target.value)}
                className={styles['time-input']}
              />
            </div>
          )}

          {/* 星期选择 */}
          {(selectedPreset === 'every_week' || selectedPreset === 'custom') && (
            <div className={styles['section']}>
              <span className={styles['section-label']}>选择星期（至少选一天）</span>
              <div className={styles['weekday-toggles']}>
                {WEEKDAY_LABELS.map((label, index) => (
                  <button
                    key={index}
                    type="button"
                    className={`${styles['weekday-btn']} ${
                      selectedWeekdays.has(index) ? styles['weekday-active'] : ''
                    }`}
                    onClick={() => toggleWeekday(index)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Cron预览 */}
          <div className={styles['section']}>
            <span className={styles['section-label']}>Cron 表达式预览</span>
            <div className={styles['cron-preview']}>
              <code className={styles['cron-code']}>{cronExpression}</code>
              {humanDescription && (
                <span className={styles['cron-human']}>
                  <ChevronRight size={12} />
                  {humanDescription}
                </span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
