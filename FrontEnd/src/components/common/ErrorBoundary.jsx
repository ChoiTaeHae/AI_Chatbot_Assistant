import { Component } from 'react'

/** 렌더 중 예외가 나도 앱 전체가 하얗게 죽지 않도록 잡고, 에러 메시지를 화면에 보여준다.
 *  (에러 바운더리가 없으면 React는 트리 전체를 언마운트해 흰 화면이 된다 = '팅김') */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  componentDidCatch(error, info) {
    console.error('[ErrorBoundary]', error, info?.componentStack)
  }
  render() {
    const { error } = this.state
    if (error) {
      return (
        <div style={{ padding: '24px', fontFamily: 'ui-monospace, monospace', color: '#dc2626', background: '#fff', minHeight: '100vh', overflow: 'auto' }}>
          <h2 style={{ fontSize: '18px', fontWeight: 700, marginBottom: '12px' }}>⚠️ 화면 오류가 발생했어요</h2>
          <p style={{ marginBottom: '12px', color: '#111', fontSize: '14px' }}>{String(error?.message || error)}</p>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontSize: '11px', color: '#666', maxHeight: '50vh', overflow: 'auto', background: '#f6f6f6', padding: '12px', borderRadius: '8px' }}>{error?.stack}</pre>
          <button
            onClick={() => this.setState({ error: null })}
            style={{ marginTop: '16px', padding: '9px 18px', background: '#0d9488', color: '#fff', borderRadius: '8px', fontWeight: 700, border: 'none', cursor: 'pointer' }}
          >
            다시 시도
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
