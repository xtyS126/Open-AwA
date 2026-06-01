/**
 * 上下文 Token 指示器 — 显示当前对话的 Token 使用量和压缩状态。
 */
import React from 'react';
import styles from './ContextIndicator.module.css';

interface ContextIndicatorProps {
  used: number;
  budget: number;
  isCompressing: boolean;
  compressionCount: number;
}

const ContextIndicator: React.FC<ContextIndicatorProps> = ({
  used,
  budget,
  isCompressing,
  compressionCount,
}) => {
  const ratio = budget > 0 ? Math.min(used / budget, 1) : 0;
  const percentage = Math.round(ratio * 100);

  const getColor = () => {
    if (ratio > 0.9) return '#dc2626';
    if (ratio > 0.7) return '#f59e0b';
    return '#22c55e';
  };

  return (
    <div className={styles.indicator} title={`Token: ${used}/${budget} (${percentage}%)`}>
      <div className={styles.barBg}>
        <div
          className={`${styles.bar} ${isCompressing ? styles.compress : ''}`}
          style={{ width: `${Math.max(percentage, 2)}%`, background: getColor() }}
        />
      </div>
      <span className={styles.text}>
        {isCompressing ? '压缩中...' : `${percentage}%`}
        {compressionCount > 0 && <span className={styles.count}> ({compressionCount})</span>}
      </span>
    </div>
  );
};

export default React.memo(ContextIndicator);
