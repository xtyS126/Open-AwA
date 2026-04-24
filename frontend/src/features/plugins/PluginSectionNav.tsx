import { NavLink } from 'react-router-dom'
import { Blocks, ShoppingCart, Settings as SettingsIcon } from 'lucide-react'
import styles from './PluginSectionNav.module.css'

const pluginNavItems = [
  {
    to: '/plugins/manage',
    label: '我的插件',
    icon: Blocks,
    end: true,
  },
  {
    to: '/plugins/config/default',
    label: '插件配置',
    icon: SettingsIcon,
    end: false,
  },
  {
    to: '/plugins/marketplace',
    label: '插件市场',
    icon: ShoppingCart,
    end: false,
  },
]

function PluginSectionNav() {
  return (
    <nav className={styles['secondary-nav']} aria-label="插件模块导航">
      {pluginNavItems.map((item) => {
        const Icon = item.icon

        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) => `${styles['nav-item']} ${isActive ? styles['active'] : ''}`.trim()}
          >
            <Icon size={18} />
            <span>{item.label}</span>
          </NavLink>
        )
      })}
    </nav>
  )
}

export default PluginSectionNav