/**
 * 定时任务日历视图组件 — 按月显示任务分布。
 */
import React, { useMemo } from 'react';
import styles from './CalendarView.module.css';

interface CalendarTask {
  id: string;
  name: string;
  cron_expression: string;
  next_run?: string;
  is_daily: boolean;
  enabled: boolean;
}

interface CalendarViewProps {
  tasks: CalendarTask[];
  currentMonth?: Date;
  onSelectDate?: (date: Date) => void;
}

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

const CalendarView: React.FC<CalendarViewProps> = ({
  tasks,
  currentMonth = new Date(),
  onSelectDate,
}) => {
  const year = currentMonth.getFullYear();
  const month = currentMonth.getMonth();

  // 构建日历网格
  const calendar = useMemo(() => {
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const startOffset = firstDay.getDay(); // 0=Sunday
    const daysInMonth = lastDay.getDate();

    const days: (Date | null)[] = [];
    // 前填充
    for (let i = 0; i < startOffset; i++) days.push(null);
    // 当月日期
    for (let d = 1; d <= daysInMonth; d++) days.push(new Date(year, month, d));
    // 后填充至完整周
    while (days.length % 7 !== 0) days.push(null);

    return days;
  }, [year, month]);

  // 构建日期→任务映射
  const taskMap = useMemo(() => {
    const map: Record<string, CalendarTask[]> = {};
    tasks.forEach((task) => {
      if (task.is_daily) {
        // 每日任务显示在所有日期
        for (let d = 1; d <= 31; d++) {
          const key = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
          if (!map[key]) map[key] = [];
          map[key].push(task);
        }
      } else if (task.next_run) {
        const dateKey = task.next_run.slice(0, 10);
        if (!map[dateKey]) map[dateKey] = [];
        map[dateKey].push(task);
      }
    });
    return map;
  }, [tasks, year, month]);

  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  return (
    <div className={styles.calendar}>
      <div className={styles.header}>
        <h3>{year} 年 {month + 1} 月</h3>
        <span className={styles.taskCount}>{tasks.length} 个任务</span>
      </div>
      <div className={styles.grid}>
        {WEEKDAYS.map((w) => (
          <div key={w} className={styles.weekday}>{w}</div>
        ))}
        {calendar.map((date, i) => {
          if (!date) return <div key={`empty-${i}`} className={styles.dayEmpty} />;
          const dateKey = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
          const dayTasks = taskMap[dateKey] || [];
          const isToday = dateKey === todayKey;

          return (
            <div
              key={dateKey}
              className={`${styles.day} ${isToday ? styles.today : ''} ${dayTasks.length > 0 ? styles.hasTasks : ''}`}
              onClick={() => onSelectDate?.(date)}
            >
              <span className={styles.dayNum}>{date.getDate()}</span>
              {dayTasks.length > 0 && (
                <div className={styles.dots}>
                  {dayTasks.slice(0, 3).map((t) => (
                    <span
                      key={t.id}
                      className={`${styles.dot} ${t.enabled ? styles.dotActive : styles.dotInactive}`}
                      title={t.name}
                    />
                  ))}
                  {dayTasks.length > 3 && (
                    <span className={styles.moreCount}>+{dayTasks.length - 3}</span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default React.memo(CalendarView);
