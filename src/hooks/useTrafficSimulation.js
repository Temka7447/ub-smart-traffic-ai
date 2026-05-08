import { useState, useEffect, useRef, useCallback } from 'react'

const DIRECTIONS = ['north', 'south', 'east', 'west']

const INTERSECTION_POSITIONS = [
  { id: 'A', row: 0, col: 0, label: 'A' },
  { id: 'B', row: 0, col: 1, label: 'B' },
  { id: 'C', row: 0, col: 2, label: 'C' },
  { id: 'D', row: 1, col: 0, label: 'D' },
  { id: 'E', row: 1, col: 1, label: 'E' },
  { id: 'F', row: 1, col: 2, label: 'F' },
  { id: 'G', row: 2, col: 0, label: 'G' },
  { id: 'H', row: 2, col: 1, label: 'H' },
  { id: 'I', row: 2, col: 2, label: 'I' },
]

const createInitialQueues = (peakHour, heavyNorth) => ({
  north: peakHour ? (heavyNorth ? 18 : 12) : (heavyNorth ? 14 : 6),
  south: peakHour ? 10 : 5,
  east: peakHour ? 8 : 4,
  west: peakHour ? 9 : 5,
})

const computeAIGreenTime = (queues, busBonus) => {
  const scores = {}
  DIRECTIONS.forEach(dir => {
    scores[dir] = queues[dir] + (busBonus && dir === 'north' ? 10 : 0)
  })
  const total = Object.values(scores).reduce((a, b) => a + b, 0) || 1
  const greenTimes = {}
  DIRECTIONS.forEach(dir => {
    const ratio = scores[dir] / total
    greenTimes[dir] = Math.max(10, Math.min(60, Math.round(ratio * 120)))
  })
  return greenTimes
}

export function useTrafficSimulation() {
  const [mode, setMode] = useState('fixed') // 'fixed' | 'ai'
  const [peakHour, setPeakHour] = useState(false)
  const [heavyNorth, setHeavyNorth] = useState(false)
  const [isRunning, setIsRunning] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [activeDir, setActiveDir] = useState('north')
  const [phaseTimer, setPhaseTimer] = useState(30)
  const [queues, setQueues] = useState(createInitialQueues(false, false))
  const [totalPassed, setTotalPassed] = useState(0)
  const [waitTimes, setWaitTimes] = useState({ fixed: [], ai: [] })
  const [vehicles, setVehicles] = useState([])
  const [intersections, setIntersections] = useState(
    INTERSECTION_POSITIONS.map(pos => ({
      ...pos,
      queues: { north: 3, south: 3, east: 3, west: 3 },
      activeDir: DIRECTIONS[Math.floor(Math.random() * 4)],
      timer: Math.floor(Math.random() * 30),
    }))
  )
  const [simTime, setSimTime] = useState(0)
  const [history, setHistory] = useState([])

  const tickRef = useRef(null)
  const frameRef = useRef(0)
  const vehicleIdRef = useRef(0)
  const dirIndexRef = useRef(0)
  const phaseTimerRef = useRef(30)

  const nextVehicleId = () => {
    vehicleIdRef.current += 1
    return vehicleIdRef.current
  }

  const spawnVehicle = useCallback((dir, currentMode) => {
    const isVertical = dir === 'north' || dir === 'south'
    const x = dir === 'east' ? -30 : dir === 'west' ? 830 : dir === 'north' ? 380 : 420
    const y = dir === 'south' ? -30 : dir === 'north' ? 530 : isVertical ? 250 : 270
    const types = ['car', 'car', 'car', 'bus', 'truck']
    return {
      id: nextVehicleId(),
      dir,
      type: types[Math.floor(Math.random() * types.length)],
      x, y,
      passed: false,
      waiting: false,
      color: dir === 'north' ? '#ff6d00' : dir === 'south' ? '#00e5ff' : dir === 'east' ? '#ffd600' : '#c653ff',
    }
  }, [])

  const reset = useCallback(() => {
    clearInterval(tickRef.current)
    setIsRunning(false)
    setActiveDir('north')
    setPhaseTimer(30)
    phaseTimerRef.current = 30
    dirIndexRef.current = 0
    frameRef.current = 0
    const q = createInitialQueues(peakHour, heavyNorth)
    setQueues(q)
    setTotalPassed(0)
    setWaitTimes({ fixed: [], ai: [] })
    setVehicles([])
    setSimTime(0)
    setHistory([])
    setIntersections(INTERSECTION_POSITIONS.map(pos => ({
      ...pos,
      queues: { north: Math.floor(Math.random() * 8) + 1, south: Math.floor(Math.random() * 8) + 1, east: Math.floor(Math.random() * 8) + 1, west: Math.floor(Math.random() * 8) + 1 },
      activeDir: DIRECTIONS[Math.floor(Math.random() * 4)],
      timer: Math.floor(Math.random() * 30),
    })))
  }, [peakHour, heavyNorth])

  useEffect(() => {
    reset()
  }, [peakHour, heavyNorth, mode])

  const tick = useCallback(() => {
    frameRef.current += 1
    const frame = frameRef.current

    // Main intersection logic
    setPhaseTimer(prev => {
      const next = prev - 1
      if (next <= 0) {
        // Advance direction
        dirIndexRef.current = (dirIndexRef.current + 1) % DIRECTIONS.length
        const newDir = DIRECTIONS[dirIndexRef.current]
        setActiveDir(newDir)

        const newTime = mode === 'fixed' ? 30 : (() => {
          setQueues(q => {
            const times = computeAIGreenTime(q, peakHour)
            phaseTimerRef.current = times[newDir]
            return q
          })
          return phaseTimerRef.current || 30
        })()
        return mode === 'fixed' ? 30 : newTime
      }
      return next
    })

    // Queue dynamics
    setQueues(prev => {
      const updated = { ...prev }
      DIRECTIONS.forEach(dir => {
        // Spawn arrivals
        const arrivalRate = peakHour ? 0.4 : 0.2
        if (Math.random() < arrivalRate) {
          updated[dir] = Math.min(40, updated[dir] + 1)
        }
      })
      // Discharge active direction
      const curDir = DIRECTIONS[dirIndexRef.current]
      if (updated[curDir] > 0) {
        const discharge = mode === 'ai' ? 2 : 1
        updated[curDir] = Math.max(0, updated[curDir] - discharge)
        setTotalPassed(p => p + discharge)
        setWaitTimes(wt => {
          const waitVal = 30 - phaseTimerRef.current
          const key = mode
          return { ...wt, [key]: [...wt[key].slice(-19), waitVal] }
        })
      }
      return updated
    })

    // Multi-intersection update
    setIntersections(prev => prev.map(inter => {
      let newTimer = inter.timer - 1
      let newActiveDir = inter.activeDir
      let newQueues = { ...inter.queues }

      // Arrivals
      DIRECTIONS.forEach(dir => {
        if (Math.random() < 0.3) newQueues[dir] = Math.min(20, newQueues[dir] + 1)
      })
      // Discharge
      if (newQueues[newActiveDir] > 0) newQueues[newActiveDir] = Math.max(0, newQueues[newActiveDir] - 1)

      if (newTimer <= 0) {
        const idx = DIRECTIONS.indexOf(newActiveDir)
        newActiveDir = DIRECTIONS[(idx + 1) % 4]
        newTimer = mode === 'fixed' ? 30 : Math.max(10, Math.min(60, newQueues[newActiveDir] * 2 + 10))
      }

      return { ...inter, timer: newTimer, activeDir: newActiveDir, queues: newQueues }
    }))

    // Vehicle animation
    if (frame % 2 === 0) {
      const spawnChance = peakHour ? 0.6 : 0.3
      if (Math.random() < spawnChance) {
        const dir = DIRECTIONS[Math.floor(Math.random() * 4)]
        setVehicles(prev => {
          if (prev.length > 20) return prev
          return [...prev, spawnVehicle(dir, mode)]
        })
      }
    }

    setVehicles(prev => {
      return prev.map(v => {
        const speed_px = 2.5
        let { x, y } = v
        const atIntersection = x > 340 && x < 460 && y > 200 && y < 340
        const isGreen = DIRECTIONS[dirIndexRef.current] === v.dir

        if (atIntersection && !isGreen) {
          return { ...v, waiting: true }
        }

        switch (v.dir) {
          case 'north': y += speed_px; break
          case 'south': y -= speed_px; break
          case 'east': x += speed_px; break
          case 'west': x -= speed_px; break
        }
        return { ...v, x, y, waiting: false }
      }).filter(v => v.x > -50 && v.x < 860 && v.y > -50 && v.y < 560)
    })

    setSimTime(t => t + 1)
    setHistory(h => {
      const totalQ = Object.values(queues).reduce((a, b) => a + b, 0)
      return [...h.slice(-59), { t: simTime, queue: totalQ }]
    })
  }, [mode, peakHour, heavyNorth, spawnVehicle, simTime, queues])

  useEffect(() => {
    if (isRunning) {
      tickRef.current = setInterval(tick, 1000 / speed)
    } else {
      clearInterval(tickRef.current)
    }
    return () => clearInterval(tickRef.current)
  }, [isRunning, tick, speed])

  const avgWait = (arr) => arr.length ? Math.round(arr.reduce((a, b) => a + b, 0) / arr.length) : 0

  const greenTimes = mode === 'ai' ? computeAIGreenTime(queues, peakHour) : { north: 30, south: 30, east: 30, west: 30 }

  return {
    mode, setMode,
    peakHour, setPeakHour,
    heavyNorth, setHeavyNorth,
    isRunning, setIsRunning,
    speed, setSpeed,
    activeDir, phaseTimer,
    queues, totalPassed,
    waitTimes,
    vehicles,
    intersections,
    simTime,
    history,
    reset,
    avgFixedWait: avgWait(waitTimes.fixed),
    avgAIWait: avgWait(waitTimes.ai),
    greenTimes,
  }
}

export { DIRECTIONS, INTERSECTION_POSITIONS }
