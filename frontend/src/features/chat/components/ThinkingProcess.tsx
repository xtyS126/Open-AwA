import React, { useState, memo, useEffect } from 'react';
import { ChevronDown, ChevronRight, BrainCircuit } from 'lucide-react';
import styles from './ThinkingProcess.module.css';

interface ThinkingProcessProps {
  children: React.ReactNode;
  defaultExpanded?: boolean;
  title?: string;
  isThinking?: boolean;
}

export const ThinkingProcess: React.FC<ThinkingProcessProps> = memo(({
  children,
  defaultExpanded = true,
  title = '思考过程',
  isThinking = false
}) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [userInteracted, setUserInteracted] = useState(false);

  const handleToggle = () => {
    setIsExpanded(!isExpanded);
    setUserInteracted(true);
  };

  // Automatically handle streaming state changes
  useEffect(() => {
    if (!userInteracted) {
      setIsExpanded(defaultExpanded);
    }
  }, [defaultExpanded, userInteracted]);

  return (
    <div className={styles.container}>
      <div 
        className={styles.header} 
        onClick={handleToggle}
      >
        <div className={styles.titleArea}>
          <BrainCircuit className={`${styles.icon} ${isThinking ? styles.spinning : ''}`} size={16} />
          <span className={styles.title}>{title}</span>
        </div>
        <div className={styles.actionArea}>
          {isExpanded ? (
            <ChevronDown className={styles.chevron} size={16} />
          ) : (
            <ChevronRight className={styles.chevron} size={16} />
          )}
        </div>
      </div>
      
      {isExpanded && (
        <div className={styles.content}>
          {children}
        </div>
      )}
    </div>
  );
});

ThinkingProcess.displayName = 'ThinkingProcess';
