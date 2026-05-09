import React, { useState } from 'react'
import { useTrafficSimulation } from './hooks/useTrafficSimulation'
import IntersectionCanvas from './components/IntersectionCanvas'
import MetricsPanel from './components/MetricsPanel'
import ControlPanel from './components/ControlPanel'
import ComparisonChart from './components/ComparisonChart'
import MultiIntersectionGrid from './components/MultiIntersectionGrid'

function Header({ simTime, isRunning }) {
  return (
    <header style={{
      padding: '20px 32px 16px',
      borderBottom: '1px solid #1e2d4a',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      flexWrap: 'wrap',
      gap: '12px',
    }}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: isRunning ? '#00e676' : '#ff1744',
            boxShadow: `0 0 10px ${isRunning ? '#00e676' : '#ff1744'}`,
            animation: isRunning ? 'pulse 1s infinite' : 'none',
          }} />
          <h1 style={{
            fontFamily: 'Sora, sans-serif',
            fontSize: '22px',
            fontWeight: 800,
            color: '#e8f0ff',
            letterSpacing: '-0.5px',
          }}>
            AI Traffic{' '}
            <span style={{
              background: 'linear-gradient(135deg, #00e676, #2979ff)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}>
              Signal
            </span>{' '}
            Simulator
          </h1>
        </div>
        <p style={{ fontSize: '12px', color: '#4a6080', marginTop: '4px', fontFamily: 'JetBrains Mono' }}>
          Гэрлэн дохионы AI зохицуулалт · Simulation · UBVibe Team
        </p>
      </div>
      <div style={{
        fontFamily: 'JetBrains Mono', fontSize: '12px', color: '#7a9cc8',
        background: '#131929', border: '1px solid #1e2d4a',
        padding: '6px 14px', borderRadius: '6px',
        display: 'flex', gap: '16px', alignItems: 'center',
      }}>
        <span>⏱ {simTime}s</span>
        <span style={{ color: '#1e2d4a' }}>|</span>
        <span style={{ color: isRunning ? '#00e676' : '#ff1744' }}>
          {isRunning ? '● Ажиллаж байна' : '○ Зогссон'}
        </span>
      </div>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </header>
  )
}

const TABS = [
  { id: 'main', label: '⬡ Үндсэн' },
  { id: 'multi', label: '⬢ Олон уулзвар' },
  { id: 'chart', label: '◈ Харьцуулалт' },
]

function LoadingSpinner() {
  return (
    <div style={{
      position: 'fixed',
      top: 16,
      right: 16,
      zIndex: 1200,
      background: '#131929',
      border: '1px solid #1e2d4a',
      borderRadius: '10px',
      padding: '8px 12px',
      display: 'flex',
      alignItems: 'center',
      gap: '10px',
      color: '#7a9cc8',
      fontFamily: 'JetBrains Mono',
      fontSize: '11px',
    }}>
      <span style={{
        width: 12,
        height: 12,
        borderRadius: '50%',
        border: '2px solid #1e2d4a',
        borderTopColor: '#00e676',
        animation: 'spin 0.8s linear infinite',
      }} />
      Loading backend...
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}

function ErrorToast({ message }) {
  return (
    <div style={{
      position: 'fixed',
      right: 16,
      bottom: 16,
      zIndex: 1200,
      background: '#2b1116',
      border: '1px solid #6d1b2a',
      borderRadius: '10px',
      padding: '10px 12px',
      color: '#ff8a9c',
      fontSize: '12px',
      fontFamily: 'Sora, sans-serif',
      maxWidth: '360px',
      boxShadow: '0 8px 24px rgba(0, 0, 0, 0.35)',
    }}>
      API Error: {message}
    </div>
  )
}

export default function App() {
  const sim = useTrafficSimulation()
  const [activeTab, setActiveTab] = useState('main')

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Header simTime={sim.simTime} isRunning={sim.isRunning} />
      {sim.isLoading && <LoadingSpinner />}
      {!sim.isLoading && sim.error && <ErrorToast message={sim.error} />}

      {/* Tab nav */}
      <nav style={{
        display: 'flex', gap: '4px', padding: '12px 32px 0',
        borderBottom: '1px solid #1e2d4a',
      }}>
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: '8px 18px', borderRadius: '8px 8px 0 0',
              border: `1px solid ${activeTab === tab.id ? '#1e2d4a' : 'transparent'}`,
              borderBottom: activeTab === tab.id ? '1px solid #0f1528' : '1px solid #1e2d4a',
              background: activeTab === tab.id ? '#0f1528' : 'transparent',
              color: activeTab === tab.id ? '#e8f0ff' : '#4a6080',
              fontSize: '12px', fontWeight: 600, cursor: 'pointer',
              fontFamily: 'Sora, sans-serif',
              marginBottom: '-1px',
              transition: 'all 0.2s',
            }}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {/* Content */}
      <main style={{ flex: 1, padding: '24px 32px', maxWidth: '1400px', width: '100%', margin: '0 auto' }}>

        {activeTab === 'main' && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 320px',
            gridTemplateRows: 'auto',
            gap: '20px',
          }}>
            {/* Left: Canvas + Controls */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{
                background: '#0d1420',
                border: '1px solid #1e2d4a',
                borderRadius: '14px',
                overflow: 'hidden',
                padding: '16px',
              }}>
                <div style={{
                  fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em',
                  marginBottom: '12px', fontFamily: 'JetBrains Mono'
                }}>
                  ГЭРЛЭН ДОХИОНЫ СИМУЛЯЦ · {sim.mode === 'ai' ? 'AI ГОРИМ' : 'ТОГТМОЛ ГОРИМ'}
                </div>
                <IntersectionCanvas
                 activeDir={sim.activeDir}
                 phaseTimer={sim.phaseTimer}
                 signalState={sim.signalState}
                 queues={sim.queues}
                 vehicles={sim.vehicles}
                 mode={sim.mode}
                />
              </div>

              <ControlPanel
                mode={sim.mode} setMode={sim.setMode}
                peakHour={sim.peakHour} setPeakHour={sim.setPeakHour}
                heavyNorth={sim.heavyNorth} setHeavyNorth={sim.setHeavyNorth}
                isRunning={sim.isRunning} setIsRunning={sim.setIsRunning}
                speed={sim.speed} setSpeed={sim.setSpeed}
                reset={sim.reset}
              />
            </div>

            {/* Right: Metrics */}
            <MetricsPanel
              queues={sim.queues}
              activeDir={sim.activeDir}
              phaseTimer={sim.phaseTimer}
              totalPassed={sim.totalPassed}
              mode={sim.mode}
              avgFixedWait={sim.avgFixedWait}
              avgAIWait={sim.avgAIWait}
              greenTimes={sim.greenTimes}
              simTime={sim.simTime}
              peakHour={sim.peakHour}
              heavyNorth={sim.heavyNorth}
            />
          </div>
        )}

        {activeTab === 'multi' && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: '280px 1fr',
            gap: '20px',
            alignItems: 'start',
          }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <ControlPanel
                mode={sim.mode} setMode={sim.setMode}
                peakHour={sim.peakHour} setPeakHour={sim.setPeakHour}
                heavyNorth={sim.heavyNorth} setHeavyNorth={sim.setHeavyNorth}
                isRunning={sim.isRunning} setIsRunning={sim.setIsRunning}
                speed={sim.speed} setSpeed={sim.setSpeed}
                reset={sim.reset}
              />
            </div>

            <div style={{
              background: '#0d1420', border: '1px solid #1e2d4a',
              borderRadius: '14px', padding: '20px',
            }}>
              <div style={{ fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em', marginBottom: '16px', fontFamily: 'JetBrains Mono' }}>
                3×3 УУЛЗВАРЫН СҮЛЖЭЭ · {sim.mode === 'ai' ? 'AI ЗОХИЦУУЛАЛТ' : 'ТОГТМОЛ ЦИКЛ'}
              </div>
              <MultiIntersectionGrid intersections={sim.intersections} />
              <div style={{ marginTop: '16px', padding: '12px', background: '#080c16', borderRadius: '8px', border: '1px solid #1e2d4a' }}>
                <div style={{ fontSize: '11px', color: '#7a9cc8', lineHeight: 1.7 }}>
                  <div style={{ marginBottom: '6px', color: '#4a6080', fontFamily: 'JetBrains Mono', fontSize: '10px', letterSpacing: '0.08em' }}>ТАЙЛБАР</div>
                  <div>🟢 Ногоон гэрэл асаж байна</div>
                  <div>🔴 Улаан гэрэл асаж байна</div>
                  <div>Цэгүүд = дарааллын машинууд</div>
                  <div>Тоо = үлдэх хугацаа (сек)</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'chart' && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: '280px 1fr',
            gap: '20px',
            alignItems: 'start',
          }}>
            <ControlPanel
              mode={sim.mode} setMode={sim.setMode}
              peakHour={sim.peakHour} setPeakHour={sim.setPeakHour}
              heavyNorth={sim.heavyNorth} setHeavyNorth={sim.setHeavyNorth}
              isRunning={sim.isRunning} setIsRunning={sim.setIsRunning}
              speed={sim.speed} setSpeed={sim.setSpeed}
              reset={sim.reset}
            />
            <ComparisonChart
              queues={sim.queues}
              greenTimes={sim.greenTimes}
              history={sim.history}
              mode={sim.mode}
            />
          </div>
        )}

      </main>
    </div>
  )
}
