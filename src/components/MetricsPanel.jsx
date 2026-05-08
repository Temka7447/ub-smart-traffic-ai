import React from 'react'

const DIR_COLORS = {
  north: '#ff6d00',
  south: '#00e5ff',
  east: '#ffd600',
  west: '#c653ff',
}

const DIR_LABELS = {
  north: 'Хойд (N)',
  south: 'Өмнөд (S)',
  east: 'Зүүн (E)',
  west: 'Баруун (W)',
}

function QueueBar({ dir, count, maxCount = 40, greenTimes, activeDir }) {
  const ratio = Math.min(1, count / maxCount)
  const isActive = activeDir === dir
  const color = DIR_COLORS[dir]
  const gt = greenTimes[dir]

  return (
    <div style={{ marginBottom: '10px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: isActive ? color : color + '50',
            boxShadow: isActive ? `0 0 8px ${color}` : 'none',
            display: 'inline-block', flexShrink: 0
          }} />
          <span style={{ fontSize: '12px', color: isActive ? color : '#7a9cc8', fontWeight: isActive ? 600 : 400 }}>
            {DIR_LABELS[dir]}
          </span>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <span style={{ fontSize: '10px', color: '#4a6080', fontFamily: 'JetBrains Mono' }}>
            {gt}s
          </span>
          <span style={{ fontSize: '12px', color: '#e8f0ff', fontFamily: 'JetBrains Mono', fontWeight: 600 }}>
            {count}
          </span>
        </div>
      </div>
      <div style={{ height: '5px', background: '#1e2d4a', borderRadius: '3px', overflow: 'hidden' }}>
        <div style={{
          height: '100%',
          width: `${ratio * 100}%`,
          background: isActive ? color : color + '60',
          borderRadius: '3px',
          boxShadow: isActive ? `0 0 6px ${color}` : 'none',
          transition: 'width 0.3s ease',
        }} />
      </div>
    </div>
  )
}

export default function MetricsPanel({
  queues, activeDir, phaseTimer, totalPassed,
  mode, avgFixedWait, avgAIWait, greenTimes, simTime, peakHour, heavyNorth
}) {
  const totalQueue = Object.values(queues).reduce((a, b) => a + b, 0)
  const dirs = ['north', 'south', 'east', 'west']
  const improvement = avgFixedWait > 0 && avgAIWait > 0
    ? Math.round(((avgFixedWait - avgAIWait) / avgFixedWait) * 100)
    : 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

      {/* Active Light */}
      <div style={{
        background: '#131929',
        border: '1px solid #1e2d4a',
        borderRadius: '12px',
        padding: '14px',
      }}>
        <div style={{ fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em', marginBottom: '10px', fontFamily: 'JetBrains Mono' }}>
          ИДЭВХТЭЙ ГЭРЭЛ
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{
            width: 52, height: 52, borderRadius: '50%',
            background: DIR_COLORS[activeDir] + '20',
            border: `2px solid ${DIR_COLORS[activeDir]}`,
            boxShadow: `0 0 20px ${DIR_COLORS[activeDir]}60`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'JetBrains Mono', fontSize: '20px', fontWeight: 700,
            color: DIR_COLORS[activeDir], flexShrink: 0
          }}>
            {phaseTimer}
          </div>
          <div>
            <div style={{ fontSize: '16px', fontWeight: 700, color: DIR_COLORS[activeDir] }}>
              {DIR_LABELS[activeDir]}
            </div>
            <div style={{ fontSize: '11px', color: '#7a9cc8', marginTop: '2px' }}>
              {mode === 'ai' ? `AI хуваарьт (${greenTimes[activeDir]}s)` : 'Тогтмол 30 сек'}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
          {dirs.map(dir => (
            <div key={dir} style={{
              flex: 1, padding: '6px 4px', borderRadius: '6px',
              background: activeDir === dir ? DIR_COLORS[dir] + '20' : '#0d1420',
              border: `1px solid ${activeDir === dir ? DIR_COLORS[dir] : '#1e2d4a'}`,
              textAlign: 'center',
            }}>
              <div style={{ fontSize: '9px', color: DIR_COLORS[dir], fontWeight: 600 }}>
                {dir[0].toUpperCase()}
              </div>
              <div style={{
                width: 6, height: 6, borderRadius: '50%', margin: '4px auto',
                background: activeDir === dir ? '#00e676' : '#ff1744',
                boxShadow: `0 0 6px ${activeDir === dir ? '#00e676' : '#ff1744'}`,
              }} />
            </div>
          ))}
        </div>
      </div>

      {/* Queue Lengths */}
      <div style={{
        background: '#131929',
        border: '1px solid #1e2d4a',
        borderRadius: '12px',
        padding: '14px',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <span style={{ fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em', fontFamily: 'JetBrains Mono' }}>
            ДАРААЛЛЫН УРТ
          </span>
          <span style={{ fontSize: '11px', color: '#e8f0ff', fontFamily: 'JetBrains Mono' }}>
            Нийт: <strong>{totalQueue}</strong>
          </span>
        </div>
        {dirs.map(dir => (
          <QueueBar
            key={dir}
            dir={dir}
            count={queues[dir]}
            greenTimes={greenTimes}
            activeDir={activeDir}
          />
        ))}
      </div>

      {/* Performance */}
      <div style={{
        background: '#131929',
        border: '1px solid #1e2d4a',
        borderRadius: '12px',
        padding: '14px',
      }}>
        <div style={{ fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em', marginBottom: '12px', fontFamily: 'JetBrains Mono' }}>
          ГҮЙЦЭТГЭЛИЙН ҮЗҮҮЛЭЛТ
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '10px' }}>
          {[
            { label: 'Нийт нэвтэрсэн', value: totalPassed, unit: 'машин', color: '#00e5ff' },
            { label: 'Нийт дараалал', value: totalQueue, unit: 'машин', color: '#ffd600' },
          ].map(({ label, value, unit, color }) => (
            <div key={label} style={{
              background: '#0d1420', borderRadius: '8px', padding: '10px',
              border: '1px solid #1e2d4a',
            }}>
              <div style={{ fontSize: '10px', color: '#4a6080', marginBottom: '4px' }}>{label}</div>
              <div style={{ fontSize: '20px', fontWeight: 700, color, fontFamily: 'JetBrains Mono' }}>{value}</div>
              <div style={{ fontSize: '9px', color: '#4a6080' }}>{unit}</div>
            </div>
          ))}
        </div>

        <div style={{ fontSize: '10px', color: '#4a6080', marginBottom: '8px' }}>Дундаж хүлээлт (сек)</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
          <div style={{
            background: '#1a0d0d', border: '1px solid #3d1515', borderRadius: '8px', padding: '10px', textAlign: 'center'
          }}>
            <div style={{ fontSize: '9px', color: '#7a4040', marginBottom: '4px' }}>Тогтмол</div>
            <div style={{ fontSize: '22px', fontWeight: 700, color: '#ff6b6b', fontFamily: 'JetBrains Mono' }}>
              {avgFixedWait}s
            </div>
          </div>
          <div style={{
            background: '#001a0d', border: '1px solid #004d1a', borderRadius: '8px', padding: '10px', textAlign: 'center'
          }}>
            <div style={{ fontSize: '9px', color: '#007a33', marginBottom: '4px' }}>AI горим</div>
            <div style={{ fontSize: '22px', fontWeight: 700, color: '#00e676', fontFamily: 'JetBrains Mono' }}>
              {avgAIWait}s
            </div>
          </div>
        </div>

        {improvement > 0 && (
          <div style={{
            marginTop: '10px', padding: '8px', background: '#001a0d',
            border: '1px solid #00c853', borderRadius: '8px', textAlign: 'center'
          }}>
            <span style={{ fontSize: '11px', color: '#00e676' }}>
              ↑ AI горим <strong>{improvement}%</strong> сайжруулсан
            </span>
          </div>
        )}
      </div>

      {/* Scenario */}
      <div style={{
        background: '#131929', border: '1px solid #1e2d4a',
        borderRadius: '12px', padding: '14px',
      }}>
        <div style={{ fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em', marginBottom: '10px', fontFamily: 'JetBrains Mono' }}>
          НӨХЦӨЛ БАЙДАЛ
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {[
            { label: 'Оргил цаг', active: peakHour, color: '#ff6d00' },
            { label: 'Хойд ачаалал', active: heavyNorth, color: '#c653ff' },
            { label: mode === 'ai' ? 'AI горим' : 'Тогтмол', active: true, color: mode === 'ai' ? '#00e676' : '#ffd600' },
          ].map(({ label, active, color }) => (
            <div key={label} style={{
              padding: '4px 10px', borderRadius: '20px', fontSize: '10px', fontWeight: 600,
              background: active ? color + '20' : '#0d1420',
              border: `1px solid ${active ? color : '#1e2d4a'}`,
              color: active ? color : '#4a6080',
            }}>
              {label}
            </div>
          ))}
        </div>
        <div style={{ marginTop: '10px', fontSize: '11px', color: '#4a6080', fontFamily: 'JetBrains Mono' }}>
          Хугацаа: {simTime}s
        </div>
      </div>
    </div>
  )
}
