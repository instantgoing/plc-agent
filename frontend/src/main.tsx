import React from 'react'
import ReactDOM from 'react-dom/client'
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import App from './App'
import './design-tokens.css'
import './styles.css'
import './ui-adjustments.css'
import './workbench.css'

loader.config({ monaco })
self.MonacoEnvironment = {
  getWorker() {
    return new EditorWorker()
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
