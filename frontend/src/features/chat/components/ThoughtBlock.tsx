import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Lightbulb } from 'lucide-react';
import styles from './ThoughtBlock.module.css';

interface ThoughtBlockProps {
  children: React.ReactNode;
  title?: string;
  defaultExpanded?: boolean;
}

export const ThoughtBlock: React.FC<ThoughtBlockProps> = ({
  children,
  title = '详细思考',
  defaultExpanded = false
}) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  return (
    <div className={styles.blockContainer}>
      <div 
        className={styles.header} 
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className={styles.titleArea}>
          <Lightbulb size={14} className={styles.icon} />
          <span className={styles.title}>{title}</span>
        </div>
        <div className={styles.actionArea}>
          {isExpanded ? (
            <ChevronDown size={14} className={styles.chevron} />
          ) : (
            <ChevronRight size={14} className={styles.chevron} />
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
};
