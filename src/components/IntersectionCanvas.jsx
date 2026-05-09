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

function drawCrosswalk(ctx, x, y, direction) {
  ctx.fillStyle = "rgba(255,255,255,0.9)";

  const stripeCount = 16;
  const stripeWidth = 3;
  const gap = 6;

  for (let i = 0; i < stripeCount; i++) {
    if (direction === "horizontal") {
      ctx.fillRect(x + i * (stripeWidth + gap), y, stripeWidth, 10);
    } else {
      ctx.fillRect(x, y + i * (stripeWidth + gap), 10, stripeWidth);
    }
  }
}

function drawDashedLane(ctx, x1, y1, x2, y2) {
  ctx.save();
  ctx.strokeStyle = "rgba(255,255,255,0.65)";
  ctx.lineWidth = 2;
  ctx.setLineDash([12, 10]);
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
  ctx.restore();
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
  ctx.setLineDash([20, 0])
  ctx.strokeStyle = '#ffffff'
  ctx.lineWidth = 2

  ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, cy - roadW); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(cx, cy + roadW); ctx.lineTo(cx, H); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(cx - roadW, cy); ctx.stroke()
  ctx.beginPath(); ctx.moveTo(cx + roadW, cy); ctx.lineTo(W, cy); ctx.stroke()
  ctx.setLineDash([])

  // Crosswalks
  drawCrosswalk(ctx, cx - 68, cy - 84, "horizontal")
  drawCrosswalk(ctx, cx - 68, cy + 74, "horizontal")
  drawCrosswalk(ctx, cx - 85, cy - 60, "vertical")
  drawCrosswalk(ctx, cx + 75, cy - 60, "vertical")

  // Stop lines
  ctx.strokeStyle = '#ffffffaa'
  ctx.lineWidth = 3

  // north
  ctx.beginPath()
  ctx.moveTo(cx - roadW, cy - 90)
  ctx.lineTo(cx + roadW, cy - 90)
  ctx.stroke()

  // south
  ctx.beginPath() 
  ctx.moveTo(cx - roadW, cy + 90) 
  ctx.lineTo(cx + roadW, cy + 90)
  ctx.stroke()

  // west
  ctx.beginPath()
  ctx.moveTo(cx - 90, cy - roadW)
  ctx.lineTo(cx - 90, cy + roadW)
  ctx.stroke()

  // east
  ctx.beginPath()
  ctx.moveTo(cx + 90, cy - roadW)
  ctx.lineTo(cx + 90, cy + roadW)
  ctx.stroke()

  // Extra lane dividers
  drawDashedLane(ctx, cx - 25, 0, cx - 25, H)
  drawDashedLane(ctx, cx + 25, 0, cx + 25, H)
  drawDashedLane(ctx, 0, cy - 25, W, cy - 25)
  drawDashedLane(ctx, 0, cy + 25, W, cy + 25)
  

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

function drawTrafficLight(ctx, x, y, signalState = 'green', activeDir, lightDir, hasLeftTurn = false)  {
  const isActiveDir = phaseDirections(activeDir).includes(lightDir)

  const isGreen = signalState === 'green' && isActiveDir
  const isYellow = signalState === 'yellow' && isActiveDir
  const isRed = !isGreen && !isYellow

  const r = 8
  const pad = 4
  const boxH = r * 8 + pad * 5
  const boxW = hasLeftTurn ? 44 : r * 2 + pad * 2

  ctx.fillStyle = '#111827'
  ctx.strokeStyle = '#374151'
  ctx.lineWidth = 1
  roundRect(ctx, x - r - pad, y - pad, boxW, boxH, 4)
  ctx.fill()
  ctx.stroke()

  // Red
  ctx.beginPath()
  ctx.arc(x, y + r, r, 0, Math.PI * 2)
  ctx.fillStyle = isRed ? '#ff1744' : '#3d0a12'
  if (isRed) {
    ctx.shadowColor = '#ff1744'
    ctx.shadowBlur = 12
  }
  ctx.fill()
  ctx.shadowBlur = 0

  // Yellow
  ctx.beginPath()
  ctx.arc(x, y + r * 3.5, r, 0, Math.PI * 2)
  ctx.fillStyle = isYellow ? '#ffd600' : '#3a3000'
  if (isYellow) {
    ctx.shadowColor = '#ffd600'
    ctx.shadowBlur = 12
  }
  ctx.fill()
  ctx.shadowBlur = 0

  // Green
  ctx.beginPath()
  ctx.arc(x, y + r * 6, r, 0, Math.PI * 2)
  ctx.fillStyle = isGreen ? '#00e676' : '#00331a'
  if (isGreen) {
    ctx.shadowColor = '#00e676'
    ctx.shadowBlur = 12
  }
  ctx.fill()
  ctx.shadowBlur = 0

  // Left turn arrow signal
  if (hasLeftTurn) {
    ctx.font = 'bold 18px Arial'
    ctx.textAlign = 'center'
    ctx.fillStyle = isGreen ? '#00e676' : isYellow ? '#ffd600' : '#3d0a12'
    ctx.fillText('←', x + 22, y + r * 3.8)
  }
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

function lerp(current, target, amount) {
  return current + (target - current) * amount
}

function lerpAngle(current, target, amount) {
  const delta = Math.atan2(Math.sin(target - current), Math.cos(target - current))
  return current + delta * amount
}

function smoothVehicleState(previous = {}, next) {
  const smoothing = previous.__fresh ? 0.28 : 1
  return {
    ...next,
    x: lerp(previous.x ?? next.x, next.x, smoothing),
    y: lerp(previous.y ?? next.y, next.y, smoothing),
    speed: lerp(previous.speed ?? next.speed ?? 0, next.speed ?? 0, 0.18),
    angle: lerpAngle(previous.angle ?? next.angle ?? 0, next.angle ?? 0, 0.22),
    steer: lerp(previous.steer ?? 0, next.steer ?? 0, 0.2),
    suspension: lerp(previous.suspension ?? 0, next.suspension ?? 0, 0.12),
    __fresh: true,
  }
}

function drawVehicle(ctx, v) {
  const { x, y, dir, type, waiting } = v
  const w = type === 'bus' ? 14 : type === 'truck' ? 12 : 10
  const h = type === 'bus' ? 24 : type === 'truck' ? 20 : 17
  const speed = v.speed ?? 0
  const bodyLean = (v.steer ?? 0) * 0.7
  const suspension = (v.suspension ?? 0) * Math.min(1.6, speed * 0.28)

  ctx.save()
  ctx.translate(x, y)
  ctx.rotate(v.angle ?? 0)
  ctx.translate(bodyLean, suspension)

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

  ctx.strokeStyle = '#ffffff24'
  ctx.lineWidth = 1
  ctx.stroke()

  // Windows
  ctx.fillStyle = '#ffffff30'
  roundRect(ctx, -w / 2 + 2, -h / 2 + 3, w - 4, h / 3, 2)
  ctx.fill()

  // Wheels
  ctx.fillStyle = '#05070b'
  ctx.fillRect(-w / 2 - 1.5, -h / 2 + 3, 2, 5)
  ctx.fillRect(w / 2 - 0.5, -h / 2 + 3, 2, 5)
  ctx.fillRect(-w / 2 - 1.5, h / 2 - 8, 2, 5)
  ctx.fillRect(w / 2 - 0.5, h / 2 - 8, 2, 5)

  // Headlights
  ctx.fillStyle = '#ffffffcc'
  ctx.shadowColor = '#ffffff'
  ctx.shadowBlur = 6
  ctx.fillRect(-w / 2 + 2, -h / 2 + 1, 3, 2)
  ctx.fillRect(w / 2 - 5, -h / 2 + 1, 3, 2)

  if (speed > 0.15) {
    ctx.globalAlpha = Math.min(0.35, speed / 12)
    ctx.fillStyle = DIR_COLORS[dir]
    roundRect(ctx, -w / 2 + 1, h / 2 - 1, w - 2, Math.min(10, speed * 1.4), 2)
    ctx.fill()
  }

  ctx.restore()
  ctx.shadowBlur = 0
  ctx.globalAlpha = 1
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

export default function IntersectionCanvas({ activeDir, phaseTimer, signalState, queues, vehicles, mode }) {
  const canvasRef = useRef(null)
  const propsRef = useRef({ activeDir, phaseTimer, signalState, queues, vehicles, mode })
  const displayVehiclesRef = useRef(new Map())
  const W = 500, H = 400
  const cx = W / 2, cy = H / 2

  useEffect(() => {
    propsRef.current = { activeDir, phaseTimer, signalState, queues, vehicles, mode }
 }, [activeDir, phaseTimer, signalState, queues, vehicles, mode])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let frameId = 0

    const render = () => {
      const {
        activeDir: frameActiveDir,
        phaseTimer: framePhaseTimer,
        signalState: frameSignalState = 'green',
        queues: frameQueues,
        vehicles: frameVehicles,
        mode: frameMode,
      } = propsRef.current

      ctx.clearRect(0, 0, W, H)
      drawRoad(ctx, W, H)

      // Traffic lights
      const roadW = 70
      drawTrafficLight(ctx, cx - roadW - 15, cy - roadW - 40, frameSignalState, frameActiveDir, 'north')
      drawTrafficLight(ctx, cx + roadW + 5, cy + roadW + 5, frameSignalState, frameActiveDir, 'south')
      drawTrafficLight(ctx, cx + roadW + 5, cy - roadW - 40, frameSignalState, frameActiveDir, 'east')
      drawTrafficLight(ctx, cx - roadW - 15, cy + roadW + 5, frameSignalState, frameActiveDir, 'west')

      const nextIds = new Set(frameVehicles.map(v => v.id))
      for (const id of displayVehiclesRef.current.keys()) {
        if (!nextIds.has(id)) displayVehiclesRef.current.delete(id)
      }

      frameVehicles.forEach(v => {
        const previous = displayVehiclesRef.current.get(v.id)
        const next = smoothVehicleState(previous, v)
        displayVehiclesRef.current.set(v.id, next)
        drawVehicle(ctx, next)
      })

      // Queue bars
      drawQueueBar(ctx, frameQueues, frameActiveDir, W, H)

      // Phase timer
      ctx.font = '700 28px JetBrains Mono, monospace'
      ctx.textAlign = 'center'
      const phase = phaseDirections(frameActiveDir)
      ctx.fillStyle = DIR_COLORS[phase[0]]
      ctx.shadowColor = ctx.fillStyle
      ctx.shadowBlur = 20
      ctx.fillText(framePhaseTimer, cx, cy + 12)
      ctx.shadowBlur = 0

      ctx.font = '500 9px Sora, sans-serif'
      ctx.fillStyle = '#ffffff50'
      ctx.fillText(`${phase[0].toUpperCase()} + ${phase[1].toUpperCase()} GREEN`, cx, cy + 26)

      // Mode badge
      ctx.font = '600 10px JetBrains Mono, monospace'
      ctx.fillStyle = frameMode === 'ai' ? '#00e676' : '#ffd600'
      ctx.shadowColor = ctx.fillStyle
      ctx.shadowBlur = 10
      ctx.textAlign = 'left'
      ctx.fillText(frameMode === 'ai' ? 'AI CONTROL' : 'FIXED CYCLE', 10, H - 10)
      ctx.shadowBlur = 0

      frameId = requestAnimationFrame(render)
    }

    render()
    return () => cancelAnimationFrame(frameId)
  }, [])

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
