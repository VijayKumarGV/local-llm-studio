/**
 * State Management & Event Bus for Local LLM Studio
 */

export const state = {
  conversations: [],
  projects: [],
  currentConversationId: null,
  currentConversation: null,
  activeProjectFilter: null,
  activeAttachments: [],
  activeArtifacts: [],
  isStreaming: false,
  currentAbortController: null,
  models: [],
  settings: {},
  tools: {
    webSearch: false,
    codeExecution: false,
    thinkDeeply: false
  }
};

const listeners = {};

export function on(event, callback) {
  if (!listeners[event]) listeners[event] = [];
  listeners[event].push(callback);
}

export function emit(event, data) {
  if (listeners[event]) {
    listeners[event].forEach(cb => cb(data));
  }
}
