import React, { useEffect, useRef } from 'react'

const DIR_COLORS = {
  north: '#ff6d00',
  south: '#00e5ff',
  east: '#ffd600',
  west: '#c653ff',
}

const LIGHT_COLORS = {
  green: '#00e676',
  red: '#ff1744',
  yellow: '#ffd600',
}

function phaseDirections(activeDir) {
  return activeDir === 'north' || activeDir === 'south'
    ? ['north', 'south']
    : ['east', 'west']
}

function drawRoad(ctx, W, H) {
  // Background
  ctx.fillStyle = '#0d1420'
  ctx.fillRect(0, 0, W, H)

  const cx = W / 2, cy = H / 2
  const roadW = 70

  // Road surfaces
  ctx.fillStyle = '#1e2533'
  ctx.fillRect(cx - roadW, 0, roadW * 2, H)
  ctx.fillRect(0, cy - roadW, W, roadW * 2)

  // Intersection box
  ctx.fillStyle = '#252d40'
  ctx.fillRect(cx - roadW, cy - roadW, roadW * 2, roadW * 2)

  // Road edges
  ctx.strokeStyle = '#3a4560'
  ctx.lineWidth = 2
  ;[cx - roadW, cx + roadW].forEach(x => {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, cy - roadW); ctx.stroke()
    ctx.beginPath(); ctx.moveTo(x, cy + roadW); ctx.lineTo(x, H); ctx.stroke()
  })
  ;[cy - roadW, cy + roadW].forEach(y => {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(cx - roadW, y); ctx.stroke()
    ctx.beginPath(); ctx.moveTo(cx + roadW, y); ctx.lineTo(W, y); ctx.stroke()
  })

  // Dashed center lines
  ctx.setLineDash([20, 15])
  ctx.strokeStyle = '#ffffff30'
  ctx.lineWidth = 2

  ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, cy - roadW); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(cx, cy + roadW); ctx.lineTo(cx, H); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(cx - roadW, cy); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(cx + roadW, cy); ctx.lineTo(W, cy); ctx.stroke()
  ctx.setLineDash([])

  // Crosswalks
  const cwW = 5, cwGap = 10, cwLen = 30
  ctx.fillStyle = '#ffffff18'
  for (let i = 0; i < 5; i++) {
    // North crosswalk
    ctx.fillRect(cx - roadW + i * (cwW + cwGap), cy - roadW - cwLen, cwW, cwLen)
    // South crosswalk
    ctx.fillRect(cx - roadW + i * (cwW + cwGap), cy + roadW, cwW, cwLen)
  }

  // Direction labels
  ctx.font = '600 11px Sora, sans-serif'
  ctx.textAlign = 'center'
  ;[
    { label: 'N', x: cx, y: 22, c: DIR_COLORS.north },
    { label: 'S', x: cx, y: H - 10, c: DIR_COLORS.south },
    { label: 'E', x: W - 12, y: cy + 5, c: DIR_COLORS.east },
    { label: 'W', x: 12, y: cy + 5, c: DIR_COLORS.west },
  ].forEach(({ label, x, y, c }) => {
    ctx.fillStyle = c
    ctx.fillText(label, x, y)
  })
}

function drawTrafficLight(ctx, x, y, phase, activeDir, lightDir) {
  const isGreen = phaseDirections(activeDir).includes(lightDir)
  const r = 8
  const pad = 4
  const boxH = r * 6 + pad * 4
  const boxW = r * 2 + pad * 2

  // Housing
  ctx.fillStyle = '#111827'
  ctx.strokeStyle = '#374151'
  ctx.lineWidth = 1
  roundRect(ctx, x - r - pad, y - pad, boxW, boxH, 4)
  ctx.fill(); ctx.stroke()

  // Red
  ctx.beginPath()
  ctx.arc(x, y + r, r, 0, Math.PI * 2)
  ctx.fillStyle = !isGreen ? '#ff1744' : '#3d0a12'
  if (!isGreen) { ctx.shadowColor = '#ff1744'; ctx.shadowBlur = 12 }
  ctx.fill()
  ctx.shadowBlur = 0

  // Green
  ctx.beginPath()
  ctx.arc(x, y + r * 4, r, 0, Math.PI * 2)
  ctx.fillStyle = isGreen ? '#00e676' : '#00331a'
  if (isGreen) { ctx.shadowColor = '#00e676'; ctx.shadowBlur = 12 }
  ctx.fill()
  ctx.shadowBlur = 0
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.lineTo(x + w - r, y)
  ctx.quadraticCurveTo(x + w, y, x + w, y + r)
  ctx.lineTo(x + w, y + h - r)
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
  ctx.lineTo(x + r, y + h)
  ctx.quadraticCurveTo(x, y + h, x, y + h - r)
  ctx.lineTo(x, y + r)
  ctx.quadraticCurveTo(x, y, x + r, y)
  ctx.closePath()
}

function drawVehicle(ctx, v) {
  const { x, y, dir, type, waiting } = v
  const isVert = dir === 'north' || dir === 'south'
  const w = type === 'bus' ? (isVert ? 14 : 22) : type === 'truck' ? (isVert ? 12 : 18) : isVert ? 10 : 16
  const h = type === 'bus' ? (isVert ? 22 : 14) : type === 'truck' ? (isVert ? 18 : 12) : isVert ? 16 : 10

  ctx.save()
  ctx.translate(x, y)

  // Glow for waiting vehicles
  if (waiting) {
    ctx.shadowColor = DIR_COLORS[dir]
    ctx.shadowBlur = 8
  }

  // Body
  ctx.fillStyle = DIR_COLORS[dir]
  ctx.globalAlpha = waiting ? 0.6 : 0.9
  roundRect(ctx, -w / 2, -h / 2, w, h, 3)
  ctx.fill()

  // Windows
  ctx.fillStyle = '#ffffff30'
  if (isVert) {
    ctx.fillRect(-w / 2 + 2, -h / 2 + 2, w - 4, h / 3)
  } else {
    ctx.fillRect(-w / 2 + 2, -h / 2 + 2, w / 3, h - 4)
  }

  // Headlights
  ctx.fillStyle = '#ffffffcc'
  ctx.shadowColor = '#ffffff'
  ctx.shadowBlur = 6
  if (dir === 'south') { ctx.fillRect(-w / 2 + 2, h / 2 - 3, 3, 2); ctx.fillRect(w / 2 - 5, h / 2 - 3, 3, 2) }
  if (dir === 'north') { ctx.fillRect(-w / 2 + 2, -h / 2 + 1, 3, 2); ctx.fillRect(w / 2 - 5, -h / 2 + 1, 3, 2) }
  if (dir === 'east') { ctx.fillRect(w / 2 - 3, -h / 2 + 2, 2, 3); ctx.fillRect(w / 2 - 3, h / 2 - 5, 2, 3) }
  if (dir === 'west') { ctx.fillRect(-w / 2 + 1, -h / 2 + 2, 2, 3); ctx.fillRect(-w / 2 + 1, h / 2 - 5, 2, 3) }

  ctx.restore()
  ctx.shadowBlur = 0
}

function drawQueueBar(ctx, queues, activeDir, W, H) {
  const cx = W / 2, cy = H / 2
  const maxQ = 40
  const barLen = 50

  const bars = [
    { dir: 'north', x: cx - 90, y: 30, label: 'N' },
    { dir: 'south', x: cx + 20, y: H - 30, label: 'S' },
    { dir: 'east', x: W - 30, y: cy - 40, label: 'E' },
    { dir: 'west', x: 30, y: cy + 20, label: 'W' },
  ]

  bars.forEach(({ dir, x, y, label }) => {
    const ratio = Math.min(1, queues[dir] / maxQ)
    const isActive = phaseDirections(activeDir).includes(dir)

    // Background bar
    ctx.fillStyle = '#ffffff10'
    ctx.fillRect(x - barLen / 2, y - 4, barLen, 8)

    // Fill
    ctx.fillStyle = isActive ? DIR_COLORS[dir] : DIR_COLORS[dir] + '80'
    if (isActive) { ctx.shadowColor = DIR_COLORS[dir]; ctx.shadowBlur = 8 }
    ctx.fillRect(x - barLen / 2, y - 4, barLen * ratio, 8)
    ctx.shadowBlur = 0

    // Label
    ctx.font = '500 9px JetBrains Mono, monospace'
    ctx.fillStyle = DIR_COLORS[dir]
    ctx.textAlign = 'center'
    ctx.fillText(`${queues[dir]}`, x, y + 16)
  })
}

export default function IntersectionCanvas({ activeDir, phaseTimer, queues, vehicles, mode }) {
  const canvasRef = useRef(null)
  const W = 500, H = 400
  const cx = W / 2, cy = H / 2

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')

    ctx.clearRect(0, 0, W, H)
    drawRoad(ctx, W, H)

    // Traffic lights
    const roadW = 70
    drawTrafficLight(ctx, cx - roadW - 15, cy - roadW - 40, phaseTimer, activeDir, 'north')
    drawTrafficLight(ctx, cx + roadW + 5, cy + roadW + 5, phaseTimer, activeDir, 'south')
    drawTrafficLight(ctx, cx + roadW + 5, cy - roadW - 40, phaseTimer, activeDir, 'east')
    drawTrafficLight(ctx, cx - roadW - 15, cy + roadW + 5, phaseTimer, activeDir, 'west')

    // Vehicles
    vehicles.forEach(v => drawVehicle(ctx, v))

    // Queue bars
    drawQueueBar(ctx, queues, activeDir, W, H)

    // Phase timer
    ctx.font = '700 28px JetBrains Mono, monospace'
    ctx.textAlign = 'center'
    const phase = phaseDirections(activeDir)
    ctx.fillStyle = DIR_COLORS[phase[0]]
    ctx.shadowColor = ctx.fillStyle
    ctx.shadowBlur = 20
    ctx.fillText(phaseTimer, cx, cy + 12)
    ctx.shadowBlur = 0

    ctx.font = '500 9px Sora, sans-serif'
    ctx.fillStyle = '#ffffff50'
    ctx.fillText(`${phase[0].toUpperCase()} + ${phase[1].toUpperCase()} GREEN`, cx, cy + 26)

    // Mode badge
    ctx.font = '600 10px JetBrains Mono, monospace'
    ctx.fillStyle = mode === 'ai' ? '#00e676' : '#ffd600'
    ctx.shadowColor = ctx.fillStyle
    ctx.shadowBlur = 10
    ctx.textAlign = 'left'
    ctx.fillText(mode === 'ai' ? '◈ AI CONTROL' : '◫ FIXED CYCLE', 10, H - 10)
    ctx.shadowBlur = 0

  }, [activeDir, phaseTimer, queues, vehicles, mode])

  return (
    <canvas
      ref={canvasRef}
      width={W}
      height={H}
      style={{
        width: '100%',
        height: 'auto',
        borderRadius: '12px',
        display: 'block',
      }}
    />
  )
}
