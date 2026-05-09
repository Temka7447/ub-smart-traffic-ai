import React from 'react'

const Btn = ({ onClick, active, color, children, danger }) => (
  <button
    onClick={onClick}
    style={{
      padding: '8px 16px',
      borderRadius: '8px',
      border: `1px solid ${active ? color : '#1e2d4a'}`,
      background: active ? color + '20' : '#0d1420',
      color: active ? color : '#4a6080',
      fontSize: '12px',
      fontWeight: 600,
      fontFamily: 'Sora, sans-serif',
      cursor: 'pointer',
      transition: 'all 0.2s',
      boxShadow: active ? `0 0 12px ${color}40` : 'none',
    }}
  >
    {children}
  </button>
)

export default function ControlPanel({
  mode, setMode,
  peakHour, setPeakHour,
  heavyNorth, setHeavyNorth,
  isRunning, setIsRunning,
  speed, setSpeed,
  reset,
}) {
  return (
    <div style={{
      background: '#0f1528',
      border: '1px solid #1e2d4a',
      borderRadius: '12px',
      padding: '16px',
    }}>
      {/* Mode toggle */}
      <div style={{ marginBottom: '16px' }}>
        <div style={{ fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em', marginBottom: '10px', fontFamily: 'JetBrains Mono' }}>
          ГОРИМ СОНГОХ
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={() => setMode('fixed')}
            style={{
              flex: 1, padding: '10px', borderRadius: '8px',
              border: `1px solid ${mode === 'fixed' ? '#ffd600' : '#1e2d4a'}`,
              background: mode === 'fixed' ? '#ffd60015' : '#0d1420',
              color: mode === 'fixed' ? '#ffd600' : '#4a6080',
              fontSize: '12px', fontWeight: 700, cursor: 'pointer',
              fontFamily: 'Sora, sans-serif',
              boxShadow: mode === 'fixed' ? '0 0 12px #ffd60040' : 'none',
              transition: 'all 0.2s',
            }}
          >
            ◫ Тогтмол цикл
          </button>
          <button
            onClick={() => setMode('ai')}
            style={{
              flex: 1, padding: '10px', borderRadius: '8px',
              border: `1px solid ${mode === 'ai' ? '#00e676' : '#1e2d4a'}`,
              background: mode === 'ai' ? '#00e67615' : '#0d1420',
              color: mode === 'ai' ? '#00e676' : '#4a6080',
              fontSize: '12px', fontWeight: 700, cursor: 'pointer',
              fontFamily: 'Sora, sans-serif',
              boxShadow: mode === 'ai' ? '0 0 12px #00e67640' : 'none',
              transition: 'all 0.2s',
            }}
          >
            ◈ AI зохицуулалт
          </button>
        </div>
      </div>

      {/* Scenario toggles */}
      <div style={{ marginBottom: '16px' }}>
        <div style={{ fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em', marginBottom: '10px', fontFamily: 'JetBrains Mono' }}>
          НӨХЦӨЛ БАЙДАЛ
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <Btn
            onClick={() => { setPeakHour(p => !p); setIsRunning(false) }}
            active={peakHour}
            color="#ff6d00"
          >
            {peakHour ? '🟠' : '⬜'} Оргил цаг
          </Btn>
          <Btn
            onClick={() => { setHeavyNorth(h => !h); setIsRunning(false) }}
            active={heavyNorth}
            color="#c653ff"
          >
            {heavyNorth ? '🟣' : '⬜'} Хойд ачаалал
          </Btn>
        </div>
      </div>

      {/* Playback controls */}
      <div style={{ marginBottom: '16px' }}>
        <div style={{ fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em', marginBottom: '10px', fontFamily: 'JetBrains Mono' }}>
          УДИРДЛАГА
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={() => setIsRunning(r => !r)}
            style={{
              flex: 2, padding: '10px', borderRadius: '8px',
              border: `1px solid ${isRunning ? '#ff1744' : '#00e676'}`,
              background: isRunning ? '#ff174415' : '#00e67615',
              color: isRunning ? '#ff1744' : '#00e676',
              fontSize: '13px', fontWeight: 700, cursor: 'pointer',
              fontFamily: 'Sora, sans-serif',
              boxShadow: `0 0 12px ${isRunning ? '#ff174440' : '#00e67640'}`,
              transition: 'all 0.2s',
            }}
          >
            {isRunning ? '⏸ Зогсоох' : '▶ Эхлэх'}
          </button>
          <button
            onClick={reset}
            style={{
              flex: 1, padding: '10px', borderRadius: '8px',
              border: '1px solid #1e2d4a', background: '#0d1420',
              color: '#7a9cc8', fontSize: '13px', fontWeight: 600, cursor: 'pointer',
              fontFamily: 'Sora, sans-serif',
              transition: 'all 0.2s',
            }}
          >
            ↺ Reset
          </button>
        </div>
      </div>

      {/* Speed */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <span style={{ fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em', fontFamily: 'JetBrains Mono' }}>
            ХУРД
          </span>
          <span style={{ fontSize: '12px', color: '#00e5ff', fontFamily: 'JetBrains Mono', fontWeight: 600 }}>
            {speed}x
          </span>
        </div>
        <input
          type="range"
          min={0.5}
          max={4}
          step={0.5}
          value={speed}
          onChange={e => setSpeed(Number(e.target.value))}
          style={{
            width: '100%', accentColor: '#00e5ff',
            height: '4px', cursor: 'pointer',
          }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', color: '#4a6080', marginTop: '4px', fontFamily: 'JetBrains Mono' }}>
          <span>0.5x</span><span>1x</span><span>2x</span><span>4x</span>
        </div>
      </div>

      {/* Info */}
      <div style={{
        marginTop: '16px', padding: '12px', background: '#080c16',
        borderRadius: '8px', border: '1px solid #1e2d4a',
      }}>
        <div style={{ fontSize: '10px', color: '#4a6080', marginBottom: '8px', fontFamily: 'JetBrains Mono', letterSpacing: '0.08em' }}>
          ТАЙЛБАР
        </div>
        <div style={{ fontSize: '11px', color: '#7a9cc8', lineHeight: 1.6 }}>
          <div style={{ marginBottom: '6px' }}>
            <span style={{ color: '#ffd600', fontWeight: 600 }}>Тогтмол:</span> Бүх чиглэлд 30с ногоон
          </div>
          <div>
            <span style={{ color: '#00e676', fontWeight: 600 }}>AI горим:</span> Дарааллын уртаас хамаарч 10–60с хуваарилна
          </div>
        </div>
      </div>
    </div>
  )
}
