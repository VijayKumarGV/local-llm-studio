/**
 * API Client & SSE Stream Decoder for Local LLM Studio
 */

export const api = {
  async getModels() {
    const res = await fetch("/api/models");
    return res.json();
  },

  async getProjects() {
    const res = await fetch("/api/projects");
    return res.json();
  },

  async createProject(payload) {
    const res = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    return res.json();
  },

  async updateProject(id, payload) {
    const res = await fetch(`/api/projects/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    return res.json();
  },

  async deleteProject(id) {
    const res = await fetch(`/api/projects/${id}`, { method: "DELETE" });
    return res.json();
  },

  async getConversations(projectId = null, includeArchived = false) {
    let url = "/api/conversations?";
    const params = [];
    if (projectId) params.push(`project_id=${projectId}`);
    if (includeArchived) params.push(`include_archived=true`);
    const res = await fetch(url + params.join("&"));
    return res.json();
  },

  async getConversation(id) {
    const res = await fetch(`/api/conversations/${id}`);
    return res.json();
  },

  async createConversation(payload) {
    const res = await fetch("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    return res.json();
  },

  async updateConversation(id, payload) {
    const res = await fetch(`/api/conversations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    return res.json();
  },

  async deleteConversation(id) {
    const res = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
    return res.json();
  },

  async duplicateConversation(id) {
    const res = await fetch(`/api/conversations/${id}/duplicate`, { method: "POST" });
    return res.json();
  },

  async branchConversation(convId, messageId) {
    const res = await fetch(`/api/conversations/${convId}/branch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: messageId })
    });
    return res.json();
  },

  async deleteMessage(id) {
    const res = await fetch(`/api/messages/${id}`, { method: "DELETE" });
    return res.json();
  },

  async getProjectFiles(projectId) {
    const res = await fetch(`/api/projects/${projectId}/files`);
    return res.json();
  },

  async deleteFile(fileId) {
    const res = await fetch(`/api/files/${fileId}`, { method: "DELETE" });
    return res.json();
  },

  async uploadFile(formData) {
    const res = await fetch("/api/files/upload", {
      method: "POST",
      body: formData
    });
    return res.json();
  },

  async search(query) {
    const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
    return res.json();
  },

  async getSettings() {
    const res = await fetch("/api/settings");
    return res.json();
  },

  async saveSettings(payload) {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    return res.json();
  },

  async getArtifacts(conversationId = null) {
    const url = conversationId ? `/api/artifacts?conversation_id=${conversationId}` : "/api/artifacts";
    const res = await fetch(url);
    return res.json();
  },

  async exportWorkspace() {
    const res = await fetch("/api/workspace/export");
    return res.json();
  },

  async importWorkspace(data) {
    const res = await fetch("/api/workspace/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
    return res.json();
  }
};
