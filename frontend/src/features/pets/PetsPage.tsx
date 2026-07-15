/**
 * PetsPage ?? ??????
 *
 * ?????????????????????? PetSprite ?? idle ???
 * ??????/?????????????"????"???? ImportPetModal?
 */
import { useEffect, useCallback, useMemo, useState } from 'react'
import { Plus, Trash2, Check, PawPrint, Loader2, AlertCircle } from 'lucide-react'
import PetSprite from './PetSprite'
import ImportPetModal from './ImportPetModal'
import { listPets, getActivePet, setActivePet, deletePet } from './petsApi'
import type { PetResponse } from './types'
import styles from './PetsPage.module.css'

interface PetsPageProps {
  /** ??????????????????????? */
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
      setLoadError(err instanceof Error ? err.message : '????????')
    } finally {
      setLoading(false)
    }
  }, [])

  // ??????????????? loadAll?
  useEffect(() => {
    void loadAll()
  }, [loadAll])

  const handleActivate = useCallback(
    async (pet: PetResponse) => {
      // ?????????
      if (pet.id === activePetId) return
      setPendingId(pet.id)
      try {
        await setActivePet(pet.id)
        setActivePetId(pet.id)
        setPets((prev) => prev.map((item) => ({ ...item, is_active: item.id === pet.id })))
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : '??????')
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
      setLoadError(err instanceof Error ? err.message : '??????')
    } finally {
      setPendingId(null)
    }
  }, [activePetId])

  const handleDelete = useCallback(
    async (pet: PetResponse) => {
      if (!window.confirm(`????????? ${pet.display_name}?`)) return
      setPendingId(pet.id)
      try {
        await deletePet(pet.id)
        setPets((prev) => prev.filter((item) => item.id !== pet.id))
        if (activePetId === pet.id) {
          setActivePetId(null)
        }
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : '??????')
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
          <h1 className={styles.title}>????</h1>
          <span className={styles.subtitle}>Codex Ambient Pet ? ?????????</span>
        </div>
        <button type="button" className={styles.btnPrimary} onClick={() => setImportOpen(true)}>
          <Plus size={14} /> ????
        </button>
      </div>

      {loadError && (
        <p className={styles.errorBanner}>
          <AlertCircle size={14} /> {loadError}
        </p>
      )}

      {loading ? (
        <div className={styles.loading}>
          <Loader2 size={20} className="pet-spin" /> ????
        </div>
      ) : (
        <>
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>?????{builtinPets.length}?</h2>
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
            <h2 className={styles.sectionTitle}>??????{customPets.length}?</h2>
            {customPets.length === 0 ? (
              <p className={styles.empty}>?????????????"????"???</p>
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
              ????????? Ambient Pet?
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
            <span className={styles.badge + ' ' + styles.badgeBuiltin}>??</span>
          ) : (
            <span className={styles.badge + ' ' + styles.badgeCustom}>???</span>
          )}
          <span className={styles.badge + ' ' + styles.badgeVersion}>v{pet.sprite_version}</span>
        </div>
        <p className={styles.desc}>{pet.description || '????'}</p>
        <div className={styles.meta}>
          <span>{pet.frame_width}x{pet.frame_height}</span>
          <span>?</span>
          <span>{pet.columns}x{pet.rows}?? {pet.frame_count} ??</span>
        </div>
      </div>
      <div className={styles.cardActions}>
        <button
          type="button"
          className={isActive ? styles.btnActive : styles.btnPrimary}
          onClick={onActivate}
          disabled={pending || isActive}
        >
          {isActive ? <><Check size={14} /> ???</> : '??'}
        </button>
        {onDelete && (
          <button
            type="button"
            className={styles.btnDanger}
            onClick={onDelete}
            disabled={pending}
            aria-label="??"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
    </div>
  )
}
