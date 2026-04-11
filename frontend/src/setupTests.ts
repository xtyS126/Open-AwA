import '@testing-library/jest-dom';
import { createElement } from 'react';
import { vi } from 'vitest';

const routerFutureConfig = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
};

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');

  return {
    ...actual,
    BrowserRouter: ({ future, ...props }: React.ComponentProps<typeof actual.BrowserRouter>) =>
      createElement(actual.BrowserRouter, {
        ...props,
        future: future ?? routerFutureConfig,
      }),
    MemoryRouter: ({ future, ...props }: React.ComponentProps<typeof actual.MemoryRouter>) =>
      createElement(actual.MemoryRouter, {
        ...props,
        future: future ?? routerFutureConfig,
      }),
  };
});

if (!HTMLElement.prototype.scrollIntoView) {
  HTMLElement.prototype.scrollIntoView = function() {};
}

if (typeof ResizeObserver === 'undefined') {
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
