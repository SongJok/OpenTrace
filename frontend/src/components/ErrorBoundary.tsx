import { Component, ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { hasError: boolean; message: string }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error?.message || 'Unexpected error' }
  }

  componentDidCatch(error: Error, info: any) {
    console.error('UI crashed', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="h-screen w-screen bg-[var(--bg)] text-[var(--text)] flex items-center justify-center p-6">
          <div className="max-w-lg w-full bg-[var(--surface)] border border-[var(--border)] rounded-2xl p-6 space-y-3">
            <h1 className="text-lg font-semibold">界面异常</h1>
            <p className="text-sm text-[var(--text-secondary)]">{this.state.message || '页面出现异常，请刷新后重试。'}</p>
            <button
              onClick={() => window.location.reload()}
              className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm"
            >
              刷新页面
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
