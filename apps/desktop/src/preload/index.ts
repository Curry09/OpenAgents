// Spec-0073/T3: preload——只读呈现（理念 8），renderer 直连 daemon，不需要越权的 Node/IPC 能力。
// 仅暴露一个只读的运行期信息位（daemon 基址由环境变量给，便于打包后指向自定端口），保持 contextIsolation。
import { contextBridge } from 'electron'

const api = {
  daemonUrl: process.env.OPENAGENTS_DAEMON_URL ?? 'http://127.0.0.1:8765'
}

export type DesktopBridge = typeof api

contextBridge.exposeInMainWorld('openagents', api)
