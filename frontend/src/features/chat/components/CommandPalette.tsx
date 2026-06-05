import { useState, useEffect, useCallback, useRef } from 'react'
import { Zap, Search } from 'lucide-react'
import { useI18nStore } from '@/i18n'
import { magicCommandsApi, MagicCommand } from '@/shared/api/magicCommandsApi'
import styles from './CommandPalette.module.css'

interface CommandPaletteProps {
  inputValue: string
  onSelectCommand: (command: string) => void
  visible: boolean
}

export function CommandPalette({ inputValue, onSelectCommand, visible }: CommandPaletteProps) {
  const { t } = useI18nStore()
  const [commands, setCommands] = useState<MagicCommand[]>([])
  const [filtered, setFiltered] = useState<MagicCommand[]>([])
  const [selectedIndex, setSelectedIndex] = useState(0)
  const paletteRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const data = await magicCommandsApi.listCommands()
        if (!cancelled) setCommands(data.commands || [])
      } catch {
        if (!cancelled) setCommands([])
      }
    }
    load()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (!visible) {
      setSelectedIndex(0)
      return
    }
    const query = inputValue.startsWith('/') ? inputValue.slice(1).toLowerCase() : ''
    if (!query) {
      setFiltered(commands)
    } else {
      setFiltered(
        commands.filter(
          c => c.name.toLowerCase().includes(query) || c.description.toLowerCase().includes(query)
        )
      )
    }
    setSelectedIndex(0)
  }, [inputValue, commands, visible])

  useEffect(() => {
    if (!visible || filtered.length === 0) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSelectedIndex(prev => (prev + 1) % filtered.length)
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSelectedIndex(prev => (prev - 1 + filtered.length) % filtered.length)
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        if (filtered[selectedIndex]) {
          onSelectCommand(`/${filtered[selectedIndex].name}`)
        }
      } else if (e.key === 'Escape') {
        onSelectCommand('')
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [visible, filtered, selectedIndex, onSelectCommand])

  if (!visible || filtered.length === 0) return null

  return (
    <div className={styles.palette} ref={paletteRef}>
      <div className={styles.header}>
        <Zap size={14} />
        <span>{t('magicCommands.title', 'magic commands') || '魔法命令'}</span>
      </div>
      <div className={styles.list}>
        {filtered.map((cmd, idx) => (
          <div
            key={cmd.name}
            className={`${styles.item} ${idx === selectedIndex ? styles.selected : ''}`}
            onClick={() => onSelectCommand(`/${cmd.name}`)}
            onMouseEnter={() => setSelectedIndex(idx)}
          >
            <div className={styles.itemHeader}>
              <code className={styles.commandName}>/{cmd.name}</code>
              {cmd.requires_wait && <span className={styles.badge}>需等待</span>}
              {cmd.saves_memory && <span className={`${styles.badge} ${styles.memoryBadge}`}>保存记忆</span>}
              {cmd.clears_context && <span className={`${styles.badge} ${styles.clearBadge}`}>清空上下文</span>}
            </div>
            <p className={styles.description}>{cmd.description}</p>
          </div>
        ))}
      </div>
      <div className={styles.footer}>
        <kbd>↑↓</kbd> 选择 · <kbd>Enter</kbd> 确认 · <kbd>Esc</kbd> 关闭
      </div>
    </div>
  )
}
