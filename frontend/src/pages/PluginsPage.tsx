import { useState, useEffect, useRef } from 'react'
import { pluginsAPI } from '../services/api'
import { Plugin } from '../types/dashboard'
import './PluginsPage.css'

function PluginsPage() {
  const [plugins, setPlugins] = useState<Plugin[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    loadPlugins()
  }, [])

  const loadPlugins = async () => {
    try {
      const response = await pluginsAPI.getAll()
      setPlugins(response.data)
    } catch (error) {
      throw error
    } finally {
      setLoading(false)
    }
  }

  const handleToggle = async (id: string) => {
    try {
      await pluginsAPI.toggle(id)
      loadPlugins()
    } catch (error) {
      throw error
    }
  }

  const handleUninstall = async (id: string) => {
    if (!confirm('确定要卸载这个插件吗？')) return
    try {
      await pluginsAPI.uninstall(id)
      loadPlugins()
    } catch (error) {
      throw error
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0]
      if (!file.name.endsWith('.zip')) {
        alert('只支持 .zip 格式的插件包')
        return
      }

      const formData = new FormData()
      formData.append('file', file)

      try {
        setUploading(true)
        const token = localStorage.getItem('token')
        const response = await fetch('http://localhost:8000/api/plugins/upload', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${token}`
          },
          body: formData
        })

        if (response.ok) {
          alert('插件导入成功')
          loadPlugins()
        } else {
          const data = await response.json()
          alert(`插件导入失败: ${data.detail || '未知错误'}`)
        }
      } catch (error) {
        console.error('Failed to upload plugin:', error)
        alert('插件导入失败')
      } finally {
        setUploading(false)
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
      }
    }
  }

  if (loading) {
    return <div className="loading">加载中...</div>
  }

  return (
    <div className="plugins-page">
      <div className="page-header">
        <h1>插件管理</h1>
        <div style={{ display: 'flex', gap: '10px' }}>
          <input 
            type="file" 
            ref={fileInputRef} 
            style={{ display: 'none' }} 
            accept=".zip"
            onChange={handleFileUpload}
          />
          <button 
            className="btn btn-primary" 
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? '导入中...' : '导入插件'}
          </button>
          <button className="btn btn-secondary">浏览插件市场</button>
        </div>
      </div>

      <div className="plugins-grid">
        {plugins.length === 0 ? (
          <div className="empty-state">
            <p>还没有安装任何插件</p>
            <button 
              className="btn btn-primary"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              {uploading ? '导入中...' : '导入插件'}
            </button>
          </div>
        ) : (
          plugins.map((plugin) => (
            <div key={plugin.id} className="plugin-card">
              <div className="plugin-header">
                <h3>{plugin.name}</h3>
                <span className="plugin-version">v{plugin.version || '1.0.0'}</span>
              </div>
              <div className="plugin-status">
                <span className={`status-badge ${plugin.enabled ? 'enabled' : 'disabled'}`}>
                  {plugin.enabled ? '已启用' : '已禁用'}
                </span>
              </div>
              <div className="plugin-actions">
                <button
                  className={`btn ${plugin.enabled ? 'btn-secondary' : 'btn-primary'}`}
                  onClick={() => handleToggle(plugin.id)}
                >
                  {plugin.enabled ? '禁用' : '启用'}
                </button>
                <button
                  className="btn btn-danger"
                  onClick={() => handleUninstall(plugin.id)}
                >
                  卸载
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default PluginsPage
