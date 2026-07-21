/**
 * 文件块 Token 统计指示器 — 显示附件对上下文窗口的 Token 贡献。
 */
import React from 'react';
import styles from './FileChunkIndicator.module.css';

interface ChunkInfo {
  name: string;
  type: 'text' | 'image' | 'audio' | 'video' | 'file';
  tokens: number;
  size?: string;
}

interface FileChunkIndicatorProps {
  chunks: ChunkInfo[];
  budget: number;
  used: number;
  expanded?: boolean;
  onToggle?: () => void;
}

/**
 * 估算文件的 Token 数量。
 */
export function estimateTokens(_fileName: string, fileSize: number, mimeType?: string): number {
  // 图片固定 Token (基于常见模型定价)
  if (mimeType?.startsWith('image/')) {
    return 85;  // 低分辨率图片基础 token 数
  }
  // 音频: ~150 tokens/秒（粗略估算）
  if (mimeType?.startsWith('audio/')) {
    const seconds = fileSize / 16000;  // 假设 16kbps
    return Math.max(50, Math.ceil(seconds * 150));
  }
  // 视频: 帧级别 token 消耗
  if (mimeType?.startsWith('video/')) {
    return 255;  // 基础帧 token 数
  }
  // 文本: ~4 chars/token 英文, ~2 chars/token 中文
  const textTokens = Math.ceil(fileSize / 4);
  return Math.max(10, textTokens);
}

const CHUNK_COLORS: Record<string, string> = {
  text: '#2196f3',
  image: '#9c27b0',
  audio: '#ff9800',
  video: '#f44336',
  file: '#607d8b',
};

const FileChunkIndicator: React.FC<FileChunkIndicatorProps> = ({
  chunks,
  budget,
  used,
  expanded = false,
  onToggle,
}) => {
  const chunkTotal = chunks.reduce((sum, c) => sum + c.tokens, 0);
  const totalRatio = budget > 0 ? Math.min((used + chunkTotal) / budget, 1) : 0;
  const textColor = totalRatio > 0.9 ? '#dc2626' : totalRatio > 0.7 ? '#f59e0b' : '#22c55e';

  if (chunks.length === 0) return null;

  return (
    <div className={styles.container} onClick={onToggle}>
      <div className={styles.summary} style={{ color: textColor }}>
        <span className={styles.icon}>&#128206;</span>
        <span>{chunks.length} files, ~{chunkTotal.toLocaleString()} tokens</span>
        {onToggle && <span className={styles.toggle}>{expanded ? '▾' : '▸'}</span>}
      </div>

      <div className={styles.bar}>
        {chunks.map((chunk, i) => {
          const width = Math.max(2, (chunk.tokens / Math.max(chunkTotal, 1)) * 100);
          return (
            <div
              key={i}
              className={styles.segment}
              style={{
                width: `${width}%`,
                background: CHUNK_COLORS[chunk.type] || '#666',
              }}
              title={`${chunk.name}: ~${chunk.tokens} tokens (${chunk.type})`}
            />
          );
        })}
      </div>

      {expanded && (
        <div className={styles.details}>
          {chunks.map((chunk, i) => (
            <div key={i} className={styles.chunkRow}>
              <span
                className={styles.dot}
                style={{ background: CHUNK_COLORS[chunk.type] || '#666' }}
              />
              <span className={styles.chunkName}>{chunk.name}</span>
              <span className={styles.chunkType}>{chunk.type}</span>
              <span className={styles.chunkTokens}>~{chunk.tokens} tokens</span>
            </div>
          ))}
          <div className={styles.warning}>
            {totalRatio > 0.9 && 'Warning: Total context may exceed token budget'}
          </div>
        </div>
      )}
    </div>
  );
};

export default React.memo(FileChunkIndicator);
