import {
  Bell,
  Blocks,
  Layers,
  MessageSquare,
  Network,
  type LucideIcon,
} from 'lucide-react'
import type { NavigationIconKey } from './navigationManifest'

const iconByKey: Record<NavigationIconKey, LucideIcon> = {
  assistant: MessageSquare,
  workbench: Blocks,
  automations: Network,
  library: Layers,
  activity: Bell,
}

export function renderNavigationIcon(iconKey: NavigationIconKey, size = 20) {
  const Icon = iconByKey[iconKey]
  return <Icon size={size} aria-hidden="true" />
}
