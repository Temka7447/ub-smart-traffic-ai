import React from 'react'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid, BarChart, Bar, Legend,
} from 'recharts'

const CustomTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    return (
      <div style={{
        background: '#131929', border: '1px solid #1e2d4a',
        borderRadius: '8px', padding: '10px 14px',
        fontFamily: 'JetBrains Mono', fontSize: '11px',
      }}>
        {payload.map((p, i) => (
          <div key={i} style={{ color: p.color, marginBottom: '2px' }}>
            {p.name}: <strong>{p.value}</strong>
          </div>
        ))}
      </div>
    )
  }
  return null
}

export default function ComparisonChart({ queues, greenTimes, history, mode }) {
  const dirs = ['north', 'south', 'east', 'west']
  const labels = { north: 'Хойд', south: 'Өмнөд', east: 'Зүүн', west: 'Баруун' }
  const colors = { north: '#ff6d00', south: '#00e5ff', east: '#ffd600', west: '#c653ff' }

  const barData = dirs.map(dir => ({
    name: labels[dir],
    'Дараалал': queues[dir],
    'AI ногоон (s)': greenTimes[dir],
    'Тогтмол (s)': 30,
    fill: colors[dir],
  }))

  const chartHistory = history.slice(-40).map((h, i) => ({ t: i, queue: h.queue }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

      {/* Live queue history */}
      <div style={{
        background: '#131929', border: '1px solid #1e2d4a',
        borderRadius: '12px', padding: '14px',
      }}>
        <div style={{ fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em', marginBottom: '12px', fontFamily: 'JetBrains Mono' }}>
          НИЙТ ДАРААЛАЛ (БОДИТ ЦАГ)
        </div>
        <ResponsiveContainer width="100%" height={100}>
          <AreaChart data={chartHistory}>
            <defs>
              <linearGradient id="queueGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#2979ff" stopOpacity={0.4} />
                <stop offset="95%" stopColor="#2979ff" stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis hide />
            <YAxis hide />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone" dataKey="queue" name="Дараалал"
              stroke="#2979ff" fill="url(#queueGrad)" strokeWidth={2}
              dot={false} isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Comparison bar */}
      <div style={{
        background: '#131929', border: '1px solid #1e2d4a',
        borderRadius: '12px', padding: '14px',
      }}>
        <div style={{ fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em', marginBottom: '12px', fontFamily: 'JetBrains Mono' }}>
          НОГООН ГЭРЛИЙН ХАРЬЦУУЛАЛТ
        </div>
        <ResponsiveContainer width="100%" height={120}>
          <BarChart data={barData} barSize={16}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e2d4a" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#7a9cc8', fontFamily: 'Sora' }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 9, fill: '#4a6080', fontFamily: 'JetBrains Mono' }} axisLine={false} tickLine={false} />
            <Tooltip content={<CustomTooltip />} />
            <Bar dataKey="AI ногоон (s)" fill="#00e676" radius={[3, 3, 0, 0]} isAnimationActive={false} />
            <Bar dataKey="Тогтмол (s)" fill="#ffd60060" radius={[3, 3, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
        <div style={{ display: 'flex', gap: '16px', marginTop: '8px', justifyContent: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '10px', color: '#7a9cc8' }}>
            <span style={{ width: 10, height: 10, background: '#00e676', borderRadius: '2px', display: 'inline-block' }} />
            AI горим
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '10px', color: '#7a9cc8' }}>
            <span style={{ width: 10, height: 10, background: '#ffd60060', borderRadius: '2px', display: 'inline-block' }} />
            Тогтмол
          </div>
        </div>
      </div>

      {/* Queue per direction */}
      <div style={{
        background: '#131929', border: '1px solid #1e2d4a',
        borderRadius: '12px', padding: '14px',
      }}>
        <div style={{ fontSize: '10px', color: '#4a6080', letterSpacing: '0.1em', marginBottom: '12px', fontFamily: 'JetBrains Mono' }}>
          ЧИГЛЭЛ ТУСБҮР ДАРААЛАЛ
        </div>
        <ResponsiveContainer width="100%" height={100}>
          <BarChart data={barData} barSize={24}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e2d4a" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#7a9cc8', fontFamily: 'Sora' }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 9, fill: '#4a6080' }} axisLine={false} tickLine={false} />
            <Tooltip content={<CustomTooltip />} />
            <Bar dataKey="Дараалал" radius={[3, 3, 0, 0]} isAnimationActive={false}>
              {barData.map((entry, index) => (
                <rect key={index} fill={entry.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

    </div>
  )
}
