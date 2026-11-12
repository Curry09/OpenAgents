// Spec-0073/T3: Expose only the daemon address to the renderer.
// Keep context isolation; the renderer needs no Node or IPC access.
import { contextBridge } from 'electron'

const api = {
  daemonUrl: process.env.OPENAGENTS_DAEMON_URL ?? 'http://127.0.0.1:8765'
}

export type DesktopBridge = typeof api

contextBridge.exposeInMainWorld('openagents', api)
