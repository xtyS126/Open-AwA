import React, { memo } from 'react';
import { CheckCircle2, CircleDashed, Loader2, XCircle } from 'lucide-react';
import styles from './TaskStep.module.css';

export type TaskStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

interface TaskStepProps {
  title: string;
  status: TaskStatus;
  children?: React.ReactNode;
}

export const TaskStep: React.FC<TaskStepProps> = memo(({
  title,
  status,
  children
}) => {
  const renderIcon = () => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 size={16} className={styles.iconCompleted} />;
      case 'in_progress':
        return <Loader2 size={16} className={styles.iconProgress} />;
      case 'failed':
        return <XCircle size={16} className={styles.iconFailed} />;
      case 'pending':
      default:
        return <CircleDashed size={16} className={styles.iconPending} />;
    }
  };

  return (
    <div className={styles.stepContainer}>
      <div className={styles.stepHeader}>
        <div className={styles.iconWrapper}>
          {renderIcon()}
        </div>
        <span className={`${styles.title} ${status === 'completed' ? styles.titleCompleted : ''}`}>
          {title}
        </span>
      </div>
      
      {children && (
        <div className={styles.stepContent}>
          {children}
        </div>
      )}
    </div>
  );
});

TaskStep.displayName = 'TaskStep';
