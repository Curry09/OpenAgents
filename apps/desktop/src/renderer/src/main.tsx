// Spec-0073/T3: renderer 入口——挂载 React 根 + 装 Tab 待看导航（T6）的全局键 handler。
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

const container = document.getElementById('root')
if (container === null) {
  throw new Error('缺少 #root 挂载点')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>
)
