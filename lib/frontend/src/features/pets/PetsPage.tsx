/**
 * PetsPage 宠物管理页
 *
 * 展示用户可用宠物，默认以 PetSprite 渲染 idle 帧动画
 * 内置/自定义宠物的增删与激活，点击"导入宠物"打开 ImportPetModal
 */
import { useEffect, useCallback, useMemo, useState } from 'react'
import { Plus, Trash2, Check, PawPrint, Loader2, AlertCircle } from 'lucide-react'
import PetSprite from './PetSprite'
import ImportPetModal from './ImportPetModal'
import { listPets, getActivePet, setActivePet, deletePet } from './petsApi'
import type { PetResponse } from './types'
import styles from './PetsPage.module.css'

interface PetsPageProps {
  /** 控制台渲染时隐藏外层标题与边距 */
  hideHeader?: boolean
}

export default function PetsPage(_props: PetsPageProps = {}) {
  const [pets, setPets] = useState<PetResponse[]>([])
  const [activePetId, setActivePetId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)

  const loadAll = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [list, active] = await Promise.all([listPets(), getActivePet()])
      setPets(list.pets)
      setActivePetId(active.pet_id)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : '加载宠物列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  // 初次挂载与导入模态回调均触发 loadAll
  useEffect(() => {
    void loadAll()
  }, [loadAll])

  const handleActivate = useCallback(
    async (pet: PetResponse) => {
      // 已激活则跳过
      if (pet.id === activePetId) return
      setPendingId(pet.id)
      try {
        await setActivePet(pet.id)
        setActivePetId(pet.id)
        setPets((prev) => prev.map((item) => ({ ...item, is_active: item.id === pet.id })))
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : '激活失败')
      } finally {
        setPendingId(null)
      }
    },
    [activePetId],
  )

  const handleDisable = useCallback(async () => {
    if (activePetId === null) return
    setPendingId('disable')
    try {
      await setActivePet('disable')
      setActivePetId(null)
      setPets((prev) => prev.map((item) => ({ ...item, is_active: false })))
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : '关闭失败')
    } finally {
      setPendingId(null)
    }
  }, [activePetId])

  const handleDelete = useCallback(
    async (pet: PetResponse) => {
      if (!window.confirm(`确定删除宠物 ${pet.display_name}？`)) return
      setPendingId(pet.id)
      try {
        await deletePet(pet.id)
        setPets((prev) => prev.filter((item) => item.id !== pet.id))
        if (activePetId === pet.id) {
          setActivePetId(null)
        }
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : '删除失败')
      } finally {
        setPendingId(null)
      }
    },
    [activePetId],
  )

  const builtinPets = useMemo(() => pets.filter((p) => p.is_builtin), [pets])
  const customPets = useMemo(() => pets.filter((p) => !p.is_builtin), [pets])

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div className={styles.titleBar}>
          <PawPrint size={20} className={styles.titleIcon} />
          <h1 className={styles.title}>宠物</h1>
          <span className={styles.subtitle}>Codex Ambient Pet · 桌面陪伴精灵</span>
        </div>
        <button type="button" className={styles.btnPrimary} onClick={() => setImportOpen(true)}>
          <Plus size={14} /> 导入宠物
        </button>
      </div>

      {loadError && (
        <p className={styles.errorBanner}>
          <AlertCircle size={14} /> {loadError}
        </p>
      )}

      {loading ? (
        <div className={styles.loading}>
          <Loader2 size={20} className="pet-spin" /> 加载中
        </div>
      ) : (
        <>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>内置宠物（{builtinPets.length}）</h2>
            <div className={styles.grid}>
              {builtinPets.map((pet) => (
                <PetCard
                  key={pet.id}
                  pet={pet}
                  isActive={pet.id === activePetId}
                  pending={pendingId === pet.id}
                  onActivate={() => void handleActivate(pet)}
                  onDelete={pet.is_builtin ? undefined : () => void handleDelete(pet)}
                />
              ))}
            </div>
          </section>

          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>自定义宠物（{customPets.length}）</h2>
            {customPets.length === 0 ? (
              <p className={styles.empty}>暂无自定义宠物，点击右上"导入宠物"上传</p>
            ) : (
              <div className={styles.grid}>
                {customPets.map((pet) => (
                  <PetCard
                    key={pet.id}
                    pet={pet}
                    isActive={pet.id === activePetId}
                    pending={pendingId === pet.id}
                    onActivate={() => void handleActivate(pet)}
                    onDelete={() => void handleDelete(pet)}
                  />
                ))}
              </div>
            )}
          </section>

          {activePetId !== null && (
            <button type="button" className={styles.btnGhost} onClick={() => void handleDisable()}>
              关闭当前 Ambient Pet
            </button>
          )}
        </>
      )}

      {importOpen && (
        <ImportPetModal
          onClose={() => setImportOpen(false)}
          onSuccess={() => void loadAll()}
        />
      )}
    </div>
  )
}

interface PetCardProps {
  pet: PetResponse
  isActive: boolean
  pending: boolean
  onActivate: () => void
  onDelete?: () => void
}

function PetCard({ pet, isActive, pending, onActivate, onDelete }: PetCardProps) {
  return (
    <div className={styles.card + (isActive ? ' ' + styles.cardActive : '')}>
      <div className={styles.spriteBox}>
        <PetSprite pet={pet} animationName="idle" scale={0.5} className={styles.sprite} />
      </div>
      <div className={styles.cardInfo}>
        <div className={styles.nameRow}>
          <h3 className={styles.name}>{pet.display_name}</h3>
          {pet.is_builtin ? (
            <span className={styles.badge + ' ' + styles.badgeBuiltin}>内置</span>
          ) : (
            <span className={styles.badge + ' ' + styles.badgeCustom}>自定义</span>
          )}
          <span className={styles.badge + ' ' + styles.badgeVersion}>v{pet.sprite_version}</span>
        </div>
        <p className={styles.desc}>{pet.description || '暂无描述'}</p>
        <div className={styles.meta}>
          <span>{pet.frame_width}x{pet.frame_height}</span>
          <span>·</span>
          <span>{pet.columns}x{pet.rows} 网格，共 {pet.frame_count} 帧</span>
        </div>
      </div>
      <div className={styles.cardActions}>
        <button
          type="button"
          className={isActive ? styles.btnActive : styles.btnPrimary}
          onClick={onActivate}
          disabled={pending || isActive}
        >
          {isActive ? <><Check size={14} /> 已激活</> : '激活'}
        </button>
        {onDelete && (
          <button
            type="button"
            className={styles.btnDanger}
            onClick={onDelete}
            disabled={pending}
            aria-label="删除"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
    </div>
  )
}