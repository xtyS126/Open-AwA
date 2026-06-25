/**
 * 定时任务模板选择器 — 快速创建常见定时任务。
 */
import React from 'react';
import styles from './TaskTemplateSelector.module.css';

interface TaskTemplate {
  id: string;
  name: string;
  description: string;
  cron: string;
  prompt: string;
  icon: string;
}

const TEMPLATES: TaskTemplate[] = [
  { id: 'morning-brief', name: '每日早报', description: '每天早上推送新闻摘要', cron: '0 8 * * *', prompt: '给我今天的新闻摘要和天气', icon: '[NEWS]' },
  { id: 'standup', name: '站会提醒', description: '工作日早上提醒站会', cron: '0 9 * * 1-5', prompt: '提醒团队今天的站会事项', icon: '[TASK]' },
  { id: 'weekly-report', name: '周报生成', description: '每周五生成工作总结', cron: '0 17 * * 5', prompt: '生成本周的工作总结报告', icon: '[CHART]' },
  { id: 'memory-clean', name: '记忆整理', description: '每天清理过期记忆', cron: '0 2 * * *', prompt: '运行记忆整理和归档', icon: '[CLEAN]' },
  { id: 'health-check', name: '系统检查', description: '每6小时检查系统状态', cron: '0 */6 * * *', prompt: '检查系统健康状态并报告', icon: '[HEALTH]' },
  { id: 'inbox-digest', name: '收件箱摘要', description: '每天中午推送收件箱摘要', cron: '0 12 * * *', prompt: '总结收件箱中的未读消息', icon: '[MAIL]' },
];

interface TaskTemplateSelectorProps {
  onSelect: (template: TaskTemplate) => void;
  onClose: () => void;
}

const TaskTemplateSelector: React.FC<TaskTemplateSelectorProps> = ({ onSelect, onClose }) => {
  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <h3>选择任务模板</h3>
          <button className={styles.close} onClick={onClose}>×</button>
        </div>
        <div className={styles.grid}>
          {TEMPLATES.map((tpl) => (
            <div
              key={tpl.id}
              className={styles.card}
              onClick={() => onSelect(tpl)}
            >
              <span className={styles.icon}>{tpl.icon}</span>
              <div>
                <h4>{tpl.name}</h4>
                <p>{tpl.description}</p>
                <code className={styles.cron}>{tpl.cron}</code>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default React.memo(TaskTemplateSelector);
