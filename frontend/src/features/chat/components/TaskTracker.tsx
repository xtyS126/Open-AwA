import React, { memo } from 'react';
import styles from './TaskTracker.module.css';

interface TaskTrackerProps {
  children: React.ReactNode;
  title?: string;
}

export const TaskTracker: React.FC<TaskTrackerProps> = memo(({ 
  children,
  title
}) => {
  return (
    <div className={styles.trackerContainer}>
      {title && <div className={styles.title}>{title}</div>}
      <div className={styles.stepsList}>
        {children}
      </div>
    </div>
  );
});

TaskTracker.displayName = 'TaskTracker';
