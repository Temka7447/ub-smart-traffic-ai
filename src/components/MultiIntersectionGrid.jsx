import React, { useEffect, useRef } from 'react'

const DIR_COLORS = {
  north: '#ff6d00',
  south: '#00e5ff',
  east: '#ffd600',
  west: '#c653ff',
}

const DIRECTIONS = ['north', 'south', 'east', 'west']

function MiniIntersection({ intersection, size = 80 }) {
  const canvasRef = useRef(null)
  const { queues, activeDir, timer, label } = intersection

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = size, H = size
    const cx = W / 2, cy = H / 2
    const roadW = 14

    ctx.clearRect(0, 0, W, H)

    // Background
    ctx.fillStyle = '#0d1420'
    ctx.fillRect(0, 0, W, H)

    // Roads
    ctx.fillStyle = '#1e2533'
    ctx.fillRect(cx - roadW, 0, roadW * 2, H)
    ctx.fillRect(0, cy - roadW, W, roadW * 2)

    // Intersection box
    ctx.fillStyle = '#252d40'
    ctx.fillRect(cx - roadW, cy - roadW, roadW * 2, roadW * 2)

    // Traffic lights (dots)
    const lightPositions = [
      { x: cx - roadW - 5, y: cy - roadW - 5, dir: 'north' },
      { x: cx + roadW + 1, y: cy + roadW + 1, dir: 'south' },
      { x: cx + roadW + 1, y: cy - roadW - 5, dir: 'east' },
      { x: cx - roadW - 5, y: cy + roadW + 1, dir: 'west' },
    ]

    lightPositions.forEach(({ x, y, dir }) => {
      const isGreen = activeDir === dir
      ctx.beginPath()
      ctx.arc(x + 2, y + 2, 4, 0, Math.PI * 2)
      ctx.fillStyle = isGreen ? '#00e676' : '#ff1744'
      if (isGreen) { ctx.shadowColor = '#00e676'; ctx.shadowBlur = 8 }
      else { ctx.shadowColor = '#ff1744'; ctx.shadowBlur = 4 }
      ctx.fill()
      ctx.shadowBlur = 0
    })

    // Queue visualizer (colored dots in lanes)
    DIRECTIONS.forEach(dir => {
      const count = Math.min(queues[dir], 6)
      const isActive = activeDir === dir
      for (let i = 0; i < count; i++) {
        let px, py
        const offset = i * 6 + 4
        if (dir === 'north') { px = cx - 4; py = cy - roadW - offset }
        else if (dir === 'south') { px = cx + 2; py = cy + roadW + offset }
        else if (dir === 'east') { px = cx + roadW + offset; py = cy - 4 }
        else { px = cx - roadW - offset; py = cy + 2 }

        if (px < 2 || px > W - 2 || py < 2 || py > H - 2) break

        ctx.beginPath()
        ctx.arc(px, py, 2.5, 0, Math.PI * 2)
        ctx.fillStyle = isActive ? DIR_COLORS[dir] : DIR_COLORS[dir] + '70'
        ctx.fill()
      }
    })

    // Label
    ctx.font = '700 9px JetBrains Mono'
    ctx.fillStyle = '#7a9cc8'
    ctx.textAlign = 'center'
    ctx.fillText(label, cx, H - 3)

    // Timer (tiny)
    ctx.font = '600 8px JetBrains Mono'
    ctx.fillStyle = DIR_COLORS[activeDir] || '#fff'
    ctx.fillText(timer, cx, 9)

  }, [queues, activeDir, timer, label, size])

  return (
    <canvas
      ref={canvasRef}
      width={size}
      height={size}
      style={{ display: 'block', borderRadius: '6px', border: '1px solid #1e2d4a' }}
    />
  )
}

export default function MultiIntersectionGrid({ intersections }) {
  const rows = [
    intersections.slice(0, 3),
    intersections.slice(3, 6),
    intersections.slice(6, 9),
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      {rows.map((row, ri) => (
        <div key={ri} style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          {row.map(inter => (
            <MiniIntersection key={inter.id} intersection={inter} size={80} />
          ))}
        </div>
      ))}
    </div>
  )
}
