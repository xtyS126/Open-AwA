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
  if (_dbFailTime > 0 && Date.now() - _dbFailTime < 30000) {
    console.warn('[useChatDraft] IndexedDB 不可用，草稿无法保存');
    return Promise.resolve(null);
  }

  _dbPromise = openDB(DB_NAME, 2, {
    upgrade(db, oldVersion) {
      if (oldVersion < 2 && !db.objectStoreNames.contains(DRAFT_STORE)) {
        db.createObjectStore(DRAFT_STORE);
      }
    },
  }).then((db) => db as IDBPDatabase)
    .catch(() => { _dbFailTime = Date.now(); _dbPromise = null; console.warn('[useChatDraft] IndexedDB 打开失败，草稿无法保存'); return null; });

  return _dbPromise;
}

/** 保存草稿，返回是否成功。失败时显式记录警告（草稿丢失可见），不静默忽略。 */
async function _saveDraft(sessionId: string, text: string, cursorPosition: number): Promise<boolean> {
  const db = await _getDB();
  if (!db) {
    console.warn(`[useChatDraft] 草稿未保存：IndexedDB 不可用（sessionId=${sessionId}）`);
    return false;
  }
  try {
    await db.put(DRAFT_STORE, { text, cursorPosition, updatedAt: Date.now() }, `${DRAFT_KEY_PREFIX}${sessionId}`);
    return true;
  } catch (error) {
    console.warn(`[useChatDraft] 草稿写入 IndexedDB 失败（sessionId=${sessionId}）:`, error);
    return false;
  }
}

async function _loadDraft(sessionId: string): Promise<{ text: string; cursorPosition: number } | null> {
  const db = await _getDB();
  if (!db) {
    console.warn(`[useChatDraft] 草稿读取失败：IndexedDB 不可用（sessionId=${sessionId}）`);
    return null;
  }
  try {
    const draft = await db.get(DRAFT_STORE, `${DRAFT_KEY_PREFIX}${sessionId}`);
    return draft as { text: string; cursorPosition: number } | undefined || null;
  } catch (error) {
    console.warn(`[useChatDraft] 草稿读取 IndexedDB 失败（sessionId=${sessionId}）:`, error);
    return null;
  }
}

async function _clearDraft(sessionId: string): Promise<void> {
  const db = await _getDB();
  if (!db) {
    console.warn(`[useChatDraft] 草稿清除失败：IndexedDB 不可用（sessionId=${sessionId}）`);
    return;
  }
  try {
    await db.delete(DRAFT_STORE, `${DRAFT_KEY_PREFIX}${sessionId}`);
  } catch (error) {
    console.warn(`[useChatDraft] 草稿删除 IndexedDB 失败（sessionId=${sessionId}）:`, error);
  }
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
    void _loadDraft(sessionId).then((draft) => {
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
        void _saveDraft(sessionRef.current, draftTextRef.current, draftCursorRef.current);
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => {
      if (draftTextRef.current.trim()) {
        void _saveDraft(sessionRef.current, draftTextRef.current, draftCursorRef.current);
      }
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, []);

  /** 保存草稿，返回是否成功（失败时已记录显式警告） */
  const saveDraft = useCallback(async (text: string, cursorPosition: number = 0): Promise<boolean> => {
    if (!sessionRef.current) return false;
    draftTextRef.current = text;
    draftCursorRef.current = cursorPosition;
    return _saveDraft(sessionRef.current, text, cursorPosition);
  }, []);

  const clearDraft = useCallback(async () => {
    if (!sessionRef.current) return;
    await _clearDraft(sessionRef.current);
  }, []);

  return { saveDraft, clearDraft };
}

export default useChatDraft;
