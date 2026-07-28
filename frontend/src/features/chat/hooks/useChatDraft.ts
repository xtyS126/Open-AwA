/**
 * 聊天草稿钩子 — 切换页面时自动保存输入框文本，返回时恢复。
 * 使用 IndexedDB 持久化，每个会话独立存储草稿。
 */
import { useEffect, useRef, useCallback } from 'react';
import { openDB, type IDBPDatabase } from 'idb';

const DB_NAME = 'openawa-chat';
const DRAFT_STORE = 'drafts';
const DRAFT_KEY_PREFIX = 'chat_draft_';

let _dbPromise: Promise<IDBPDatabase | null> | null = null;
let _dbFailTime = 0;

function _getDB(): Promise<IDBPDatabase | null> {
  if (_dbPromise) return _dbPromise;
  if (_dbFailTime > 0 && Date.now() - _dbFailTime < 30000) return Promise.resolve(null);

  _dbPromise = openDB(DB_NAME, 2, {
    upgrade(db, oldVersion) {
      if (oldVersion < 2 && !db.objectStoreNames.contains(DRAFT_STORE)) {
        db.createObjectStore(DRAFT_STORE);
      }
    },
  }).then((db) => db as IDBPDatabase)
    .catch(() => { _dbFailTime = Date.now(); _dbPromise = null; return null; });

  return _dbPromise;
}

async function _saveDraft(sessionId: string, text: string, cursorPosition: number): Promise<void> {
  const db = await _getDB();
  if (!db) {
    // IndexedDB 不可用时回退到 localStorage，写入失败可忽略（草稿丢失不影响主流程）
    try { localStorage.setItem(`${DRAFT_KEY_PREFIX}${sessionId}`, JSON.stringify({ text, cursorPosition })); } catch { /* localStorage 写入失败可忽略 */ }
    return;
  }
  try {
    await db.put(DRAFT_STORE, { text, cursorPosition, updatedAt: Date.now() }, `${DRAFT_KEY_PREFIX}${sessionId}`);
  } catch {
    // IndexedDB 写入失败时回退到 localStorage，localStorage 写入失败可忽略
    try { localStorage.setItem(`${DRAFT_KEY_PREFIX}${sessionId}`, JSON.stringify({ text, cursorPosition })); } catch { /* localStorage 写入失败可忽略 */ }
  }
}

async function _loadDraft(sessionId: string): Promise<{ text: string; cursorPosition: number } | null> {
  const db = await _getDB();
  if (!db) {
    try {
      const raw = localStorage.getItem(`${DRAFT_KEY_PREFIX}${sessionId}`);
      if (raw) return JSON.parse(raw);
    } catch { return null; }
    return null;
  }
  try {
    const draft = await db.get(DRAFT_STORE, `${DRAFT_KEY_PREFIX}${sessionId}`);
    return draft as { text: string; cursorPosition: number } | undefined || null;
  } catch {
    try {
      const raw = localStorage.getItem(`${DRAFT_KEY_PREFIX}${sessionId}`);
      if (raw) return JSON.parse(raw);
    } catch { return null; }
    return null;
  }
}

async function _clearDraft(sessionId: string): Promise<void> {
  const db = await _getDB();
  if (!db) { localStorage.removeItem(`${DRAFT_KEY_PREFIX}${sessionId}`); return; }
  // IndexedDB 删除失败可忽略，残留草稿不影响主流程
  try { await db.delete(DRAFT_STORE, `${DRAFT_KEY_PREFIX}${sessionId}`); } catch { /* 删除失败可忽略 */ }
  localStorage.removeItem(`${DRAFT_KEY_PREFIX}${sessionId}`);
}

interface UseChatDraftOptions {
  sessionId: string;
  onRestore?: (text: string, cursorPosition: number) => void;
}

/**
 * 聊天草稿钩子。
 *
 * 用法:
 *   const { saveDraft, clearDraft } = useChatDraft({
 *     sessionId: activeConversationId,
 *     onRestore: (text, pos) => { setInput(text); setCursor(pos); },
 *   });
 */
export function useChatDraft({ sessionId, onRestore }: UseChatDraftOptions) {
  const sessionRef = useRef(sessionId);
  const onRestoreRef = useRef(onRestore);

  // 在 useEffect 中更新 ref，避免在 render 阶段修改 ref 违反 React 纯渲染规则
  useEffect(() => {
    sessionRef.current = sessionId;
    onRestoreRef.current = onRestore;
  });

  // 挂载时恢复草稿
  useEffect(() => {
    if (!sessionId) return;
    _loadDraft(sessionId).then((draft) => {
      if (draft && draft.text && onRestoreRef.current) {
        onRestoreRef.current(draft.text, draft.cursorPosition || 0);
      }
    });
  }, [sessionId]);

  // 页面卸载/切换时自动保存草稿
  const draftTextRef = useRef('');
  const draftCursorRef = useRef(0);

  useEffect(() => {
    const handleBeforeUnload = () => {
      if (draftTextRef.current.trim()) {
        _saveDraft(sessionRef.current, draftTextRef.current, draftCursorRef.current);
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => {
      if (draftTextRef.current.trim()) {
        _saveDraft(sessionRef.current, draftTextRef.current, draftCursorRef.current);
      }
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, []);

  const saveDraft = useCallback(async (text: string, cursorPosition: number = 0) => {
    if (!sessionRef.current) return;
    draftTextRef.current = text;
    draftCursorRef.current = cursorPosition;
    await _saveDraft(sessionRef.current, text, cursorPosition);
  }, []);

  const clearDraft = useCallback(async () => {
    if (!sessionRef.current) return;
    await _clearDraft(sessionRef.current);
  }, []);

  return { saveDraft, clearDraft };
}

export default useChatDraft;
