import React, { memo } from 'react';
import { FileCode, FileText, Image as ImageIcon, File } from 'lucide-react';
import styles from './FileReference.module.css';

interface FileReferenceProps {
  fileName: string;
  filePath?: string;
  fileType?: 'code' | 'text' | 'image' | 'unknown';
  onClick?: () => void;
}

export const FileReference: React.FC<FileReferenceProps> = memo(({
  fileName,
  filePath,
  fileType = 'unknown',
  onClick
}) => {
  const getIcon = () => {
    switch (fileType) {
      case 'code':
        return <FileCode size={14} className={styles.icon} />;
      case 'text':
        return <FileText size={14} className={styles.icon} />;
      case 'image':
        return <ImageIcon size={14} className={styles.icon} />;
      default:
        // 尝试从文件名推断
        if (fileName.match(/\.(ts|tsx|js|jsx|py|go|rs|java|c|cpp|h|css|scss|html)$/i)) {
          return <FileCode size={14} className={styles.icon} />;
        }
        if (fileName.match(/\.(md|txt|json|yml|yaml|xml|csv)$/i)) {
          return <FileText size={14} className={styles.icon} />;
        }
        if (fileName.match(/\.(png|jpg|jpeg|gif|svg|webp)$/i)) {
          return <ImageIcon size={14} className={styles.icon} />;
        }
        return <File size={14} className={styles.icon} />;
    }
  };

  return (
    <button 
      className={styles.pill} 
      onClick={onClick}
      title={filePath || fileName}
      type="button"
    >
      {getIcon()}
      <span className={styles.fileName}>{fileName}</span>
    </button>
  );
});

FileReference.displayName = 'FileReference';
