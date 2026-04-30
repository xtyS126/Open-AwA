import { describe, it, expect } from 'vitest';
import { parseStream } from './streamParser';

describe('streamParser', () => {
  describe('XML Parsing', () => {
    it('should parse complete thinking block', () => {
      const text = '<thinking>\nThis is a thought process.\n</thinking>\nFinal answer';
      const result = parseStream(text);
      expect(result.isThinking).toBe(false);
      expect(result.thinkingContent).toBe('This is a thought process.');
      expect(result.finalContent).toBe('Final answer');
    });

    it('should parse incomplete thinking block and mark isThinking as true', () => {
      const text = '<thinking>\nThinking in progress...';
      const result = parseStream(text);
      expect(result.isThinking).toBe(true);
      expect(result.thinkingContent).toBe('Thinking in progress...');
      expect(result.finalContent).toBe('');
    });

    it('should parse file tags', () => {
      const text = '<files>\n<file path="src/test.ts">test.ts</file>\n</files>\nHello';
      const result = parseStream(text);
      expect(result.fileReferences).toHaveLength(1);
      expect(result.fileReferences[0]).toEqual({ path: 'src/test.ts', name: 'test.ts' });
      expect(result.finalContent).toBe('Hello');
    });

    it('should parse task tags and handle streaming updates', () => {
      let text = '<tasks>\n<task id="1" status="pending">Do something</task>\n</tasks>';
      let result = parseStream(text);
      expect(result.tasks).toHaveLength(1);
      expect(result.tasks[0]).toEqual({ id: '1', status: 'pending', title: 'Do something' });

      text = '<tasks>\n<task id="1" status="in_progress">Do something</task>\n<task id="2" status="pending">Do else</task>\n</tasks>';
      result = parseStream(text);
      expect(result.tasks).toHaveLength(2);
      expect(result.tasks[0]).toEqual({ id: '1', status: 'in_progress', title: 'Do something' });
      expect(result.tasks[1]).toEqual({ id: '2', status: 'pending', title: 'Do else' });

      text = '<tasks>\n<task id="1" status="completed">Do something</task>\n<task id="2" status="pending">Do else</task>\n</tasks>';
      result = parseStream(text);
      expect(result.tasks[0]).toEqual({ id: '1', status: 'completed', title: 'Do something' });
    });
  });

  describe('Markdown Parsing', () => {
    it('should parse markdown thinking block', () => {
      const text = '> Thinking:\n> I need to fix this.\n> Maybe here.\n\nFinal text';
      const result = parseStream(text);
      expect(result.thinkingContent).toBe('I need to fix this.\nMaybe here.');
      expect(result.isThinking).toBe(false);
      expect(result.finalContent).toBe('Final text');
    });

    it('should parse incomplete markdown thinking block as thinking', () => {
      const text = '> Thinking:\n> Processing';
      const result = parseStream(text);
      expect(result.thinkingContent).toBe('Processing');
      expect(result.isThinking).toBe(true);
      expect(result.finalContent).toBe('');
    });

    it('should parse markdown files', () => {
      const text = '**Files:**\n- `src/index.ts`\n- `package.json`\n\nText here';
      const result = parseStream(text);
      expect(result.fileReferences).toHaveLength(2);
      expect(result.fileReferences[0]).toEqual({ path: 'src/index.ts', name: 'index.ts' });
      expect(result.fileReferences[1]).toEqual({ path: 'package.json', name: 'package.json' });
      expect(result.finalContent).toBe('Text here');
    });

    it('should parse markdown tasks', () => {
      const text = '**Tasks:**\n- [x] Task 1\n- [-] Task 2\n- [ ] Task 3\n\nEnd text';
      const result = parseStream(text);
      expect(result.tasks).toHaveLength(3);
      expect(result.tasks[0]).toEqual({ id: 'md-task-1', status: 'completed', title: 'Task 1' });
      expect(result.tasks[1]).toEqual({ id: 'md-task-2', status: 'in_progress', title: 'Task 2' });
      expect(result.tasks[2]).toEqual({ id: 'md-task-3', status: 'pending', title: 'Task 3' });
      expect(result.finalContent).toBe('End text');
    });
  });
});
