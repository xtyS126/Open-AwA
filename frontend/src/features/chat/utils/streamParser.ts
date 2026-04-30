export interface FileReference {
  path: string;
  name: string;
}

export type TaskStatus = 'pending' | 'in_progress' | 'completed';

export interface TaskStep {
  id: string;
  title: string;
  status: TaskStatus;
}

export interface ParsedStreamState {
  isThinking: boolean;
  thinkingContent: string;
  fileReferences: FileReference[];
  tasks: TaskStep[];
  finalContent: string;
}

export function parseStream(text: string): ParsedStreamState {
  const state: ParsedStreamState = {
    isThinking: false,
    thinkingContent: '',
    fileReferences: [],
    tasks: [],
    finalContent: ''
  };

  if (!text) {
    return state;
  }

  // --- XML Parsing ---

  // <thinking> block
  const thinkingRegex = /<thinking>([\s\S]*?)(?:<\/thinking>|$)/gi;
  let match;
  while ((match = thinkingRegex.exec(text)) !== null) {
    state.thinkingContent += (state.thinkingContent ? '\n' : '') + match[1].trim();
    if (!text.substring(match.index).includes('</thinking>')) {
      state.isThinking = true;
    }
  }

  // <file> tags
  const fileRegex = /<file\s+path="([^"]+)">([\s\S]*?)(?:<\/file>|$)/gi;
  while ((match = fileRegex.exec(text)) !== null) {
    state.fileReferences.push({
      path: match[1],
      name: match[2].trim()
    });
  }

  // <task> tags
  const taskRegex = /<task\s+id="([^"]+)"\s+status="([^"]+)">([\s\S]*?)(?:<\/task>|$)/gi;
  while ((match = taskRegex.exec(text)) !== null) {
    const status = match[2] as TaskStatus;
    state.tasks.push({
      id: match[1],
      status: ['pending', 'in_progress', 'completed'].includes(status) ? status : 'pending',
      title: match[3].trim()
    });
  }

  // --- Markdown Parsing ---

  // Markdown thinking: blockquotes starting with "Thinking:" or "思考过程："
  const mdThinkingRegex = /(?:^|\n)>\s*(?:Thinking|思考过程)[:：]?\s*\n((?:>.*\n?)*)/gi;
  while ((match = mdThinkingRegex.exec(text)) !== null) {
    const content = match[1].replace(/^>\s?/gm, '').trim();
    if (content) {
      state.thinkingContent += (state.thinkingContent ? '\n' : '') + content;
      // It's hard to know if we are currently thinking in markdown since it's just blockquotes,
      // but if it's at the end of the text, we might be.
      if (match.index + match[0].length === text.length && !text.endsWith('\n\n')) {
        state.isThinking = true;
      }
    }
  }

  // Markdown files: "**Files:**" followed by list
  const mdFilesRegex = /(?:^|\n)\*\*Files:?\*\*\s*\n((?:-\s+`[^`]+`\s*\n?)*)/gi;
  while ((match = mdFilesRegex.exec(text)) !== null) {
    const lines = match[1].split('\n');
    for (const line of lines) {
      const fileMatch = line.match(/-\s+`([^`]+)`/);
      if (fileMatch) {
        const path = fileMatch[1];
        const name = path.split('/').pop() || path;
        state.fileReferences.push({ path, name });
      }
    }
  }

  // Markdown tasks: "**Tasks:**" followed by checklist
  // - [ ] pending, - [x] completed, - [-] in_progress
  const mdTasksRegex = /(?:^|\n)\*\*Tasks:?\*\*\s*\n((?:-\s+\[[ x-]\]\s+.*\n?)*)/gi;
  while ((match = mdTasksRegex.exec(text)) !== null) {
    const lines = match[1].split('\n');
    for (let i = 0; i < lines.length; i++) {
      const taskMatch = lines[i].match(/-\s+\[([ x-])\]\s+(.*)/);
      if (taskMatch) {
        const mark = taskMatch[1];
        const title = taskMatch[2].trim();
        let status: TaskStatus = 'pending';
        if (mark.toLowerCase() === 'x') status = 'completed';
        if (mark === '-') status = 'in_progress';
        
        state.tasks.push({
          id: `md-task-${state.tasks.length + 1}`,
          status,
          title
        });
      }
    }
  }

  // --- Clean up final content ---
  let finalContent = text
    // Remove XML tags
    .replace(/<thinking>[\s\S]*?(?:<\/thinking>|$)/gi, '')
    .replace(/<file\s+path="[^"]+">[\s\S]*?(?:<\/file>|$)/gi, '')
    .replace(/<task\s+id="[^"]+"\s+status="[^"]+">[\s\S]*?(?:<\/task>|$)/gi, '')
    .replace(/<\/?files>/gi, '')
    .replace(/<\/?tasks>/gi, '')
    // Remove Markdown blocks
    .replace(/(?:^|\n)>\s*(?:Thinking|思考过程)[:：]?\s*\n(?:>.*\n?)*/gi, '')
    .replace(/(?:^|\n)\*\*Files:?\*\*\s*\n(?:-\s+`[^`]+`\s*\n?)*/gi, '')
    .replace(/(?:^|\n)\*\*Tasks:?\*\*\s*\n(?:-\s+\[[ x-]\]\s+.*\n?)*/gi, '');

  state.finalContent = finalContent.trim();

  return state;
}
