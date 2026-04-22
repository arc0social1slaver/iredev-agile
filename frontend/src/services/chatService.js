// src/services/chatService.js
// ─────────────────────────────────────────────────────────────────────────────
// All REST API calls related to conversations and messages.
//
// Every function maps 1-to-1 to a backend endpoint.
// Components never call apiClient directly — they go through here.
//
// Expected backend contract
// ─────────────────────────
//
//  GET    /api/chats                   → Chat[]
//  POST   /api/chats                   → Chat         body: { title }
//  DELETE /api/chats/:chatId           → { ok: true }
//
//  GET    /api/chats/:chatId/messages  → Message[]
//  POST   /api/chats/:chatId/messages  → Message      body: { role, content }
//
//  POST   /api/auth/login              → { token, user }  body: { email, password }
//  POST   /api/auth/logout             → { ok: true }
//
// Chat shape:    { id, title, date, createdAt }
// Message shape: { id, chatId, role, content, artifact?, createdAt }
// ─────────────────────────────────────────────────────────────────────────────

// =============================================================================
// REST API calls for auth, chats, and messages.
//
// Auth functions work with access_token (in RAM) + refresh_token (HttpOnly
// cookie). They never read or write localStorage — that's apiClient's job.
// =============================================================================
import { get, post, put, del } from "./apiClient";
import { setAccessToken, clearAccessToken } from "./tokenStore";

// ── Auth ──────────────────────────────────────────────────────────────────────

export async function login(credentials) {
  const result = await post("/api/auth/login", credentials);
  setAccessToken(result.access_token);
  return result;
}

export async function logout() {
  try {
    await post("/api/auth/logout", {});
  } finally {
    clearAccessToken();
  }
}

export async function register(data) {
  const result = await post("/api/auth/register", data);
  setAccessToken(result.access_token);
  return result;
}

// ── Projects ──────────────────────────────────────────────────────────────────

export const fetchProjects       = ()                           => get("/api/projects");
export const createProject       = (name, description = "")    => post("/api/projects", { name, description });
export const updateProject       = (projectId, data)           => put(`/api/projects/${projectId}`, data);
export const deleteProject       = (projectId)                 => del(`/api/projects/${projectId}`);
export const fetchProjectChats   = (projectId)                 => get(`/api/projects/${projectId}/chats`);
export const createProjectChat   = (projectId, title)          => post(`/api/projects/${projectId}/chats`, { title });

// ── Chats (top-level, legacy) ─────────────────────────────────────────────────

export const fetchChats   = ()                          => get("/api/chats");
export const createChat   = (title, projectId = null)   => post("/api/chats", { title, projectId });
export const deleteChat   = (chatId)                    => del(`/api/chats/${chatId}`);
export const fetchMessages = (chatId, newSubChat)       => get(`/api/chats/${chatId}/${newSubChat}/messages`);
export const sendMessage   = (chatId, content, subChat) => post(`/api/chats/${chatId}/${subChat}/messages`, { role: "user", content });
export const startReq      = (config, chat_id)          => post(`/api/chats/process/start/${chat_id}`, { ...config });