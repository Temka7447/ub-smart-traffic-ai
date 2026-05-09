import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  connectWebSocket,
  getComparison,
  getQueueHistory,
  getSimulationState,
  setSpeed as setSpeedApi,
  startSim,
  stopSim,
  switchMode,
} from '../services/api'

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

const FIXED_GREEN_TIMES = { north: 30, south: 30, east: 30, west: 30 }

const createFallbackIntersections = () =>
  INTERSECTION_POSITIONS.map((pos) => ({
    ...pos,
    queues: { north: 3, south: 3, east: 3, west: 3 },
    activeDir: 'north',
    timer: 30,
  }))

const readNextValue = (valueOrUpdater, current) =>
  typeof valueOrUpdater === 'function' ? valueOrUpdater(current) : valueOrUpdater

export function useTrafficSimulation() {
  const [mode, setModeState] = useState('fixed')
  const [peakHour, setPeakHourState] = useState(false)
  const [heavyNorth, setHeavyNorthState] = useState(false)
  const [isRunning, setIsRunningState] = useState(false)
  const [speed, setSpeedState] = useState(1)

  const [activeDir, setActiveDir] = useState('north')
  const [phaseTimer, setPhaseTimer] = useState(30)
  const [queues, setQueues] = useState({ north: 6, south: 5, east: 4, west: 5 })
  const [totalPassed, setTotalPassed] = useState(0)
  const [waitTimes, setWaitTimes] = useState({ fixed: [], ai: [] })
  const [vehicles, setVehicles] = useState([])
  const [intersections, setIntersections] = useState(createFallbackIntersections)
  const [simTime, setSimTime] = useState(0)
  const [history, setHistory] = useState([])
  const [greenTimes, setGreenTimes] = useState(FIXED_GREEN_TIMES)
  const [avgFixedWait, setAvgFixedWait] = useState(0)
  const [avgAIWait, setAvgAIWait] = useState(0)
  const [aiActivePhase, setAiActivePhase] = useState(null)
  const [aiDecisionReason, setAiDecisionReason] = useState('')
  const [aiCongestionState, setAiCongestionState] = useState({})
  const [antiGridlockActive, setAntiGridlockActive] = useState(false)
  const [pedestrianWaiting, setPedestrianWaiting] = useState({})
  const [emergencyActive, setEmergencyActive] = useState(false)
  const [neighborPressure, setNeighborPressure] = useState({})

  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')

  const modeRef = useRef(mode)
  const peakHourRef = useRef(peakHour)
  const heavyNorthRef = useRef(heavyNorth)
  const isRunningRef = useRef(isRunning)
  const speedRef = useRef(speed)
  const queueRef = useRef(queues)
  const suppressSocketErrorRef = useRef(false)

  useEffect(() => { modeRef.current = mode }, [mode])
  useEffect(() => { peakHourRef.current = peakHour }, [peakHour])
  useEffect(() => { heavyNorthRef.current = heavyNorth }, [heavyNorth])
  useEffect(() => { isRunningRef.current = isRunning }, [isRunning])
  useEffect(() => { speedRef.current = speed }, [speed])
  useEffect(() => { queueRef.current = queues }, [queues])

  const applySnapshot = useCallback((snapshot) => {
    setModeState(snapshot.mode)
    setPeakHourState(snapshot.peakHour)
    setHeavyNorthState(snapshot.heavyNorth)
    setIsRunningState(snapshot.isRunning)
    setSpeedState(snapshot.speed)

    setActiveDir(snapshot.activeDir)
    setPhaseTimer(snapshot.phaseTimer)
    setQueues(snapshot.queues)
    setTotalPassed(snapshot.totalPassed)
    setWaitTimes(snapshot.waitTimes)
    setVehicles(snapshot.vehicles)
    setIntersections(snapshot.intersections)
    setSimTime(snapshot.simTime)
    setHistory(snapshot.history)
    setGreenTimes(snapshot.greenTimes)
    setAvgFixedWait(snapshot.avgFixedWait)
    setAvgAIWait(snapshot.avgAIWait)
    setAiActivePhase(snapshot.aiActivePhase ?? null)
    setAiDecisionReason(snapshot.aiDecisionReason ?? '')
    setAiCongestionState(snapshot.aiCongestionState ?? {})
    setAntiGridlockActive(Boolean(snapshot.antiGridlockActive))
    setPedestrianWaiting(snapshot.pedestrianWaiting ?? {})
    setEmergencyActive(Boolean(snapshot.emergencyActive))
    setNeighborPressure(snapshot.neighborPressure ?? {})

    modeRef.current = snapshot.mode
    peakHourRef.current = snapshot.peakHour
    heavyNorthRef.current = snapshot.heavyNorth
    isRunningRef.current = snapshot.isRunning
    speedRef.current = snapshot.speed
    queueRef.current = snapshot.queues
  }, [])

  const setApiError = useCallback((err, fallbackMessage = 'API server is unreachable') => {
    const message = err instanceof Error ? err.message : fallbackMessage
    setError(message || fallbackMessage)
  }, [])

  const syncSignalPlan = useCallback(async (sourceQueues = queueRef.current) => {
    if (modeRef.current !== 'ai') {
      setGreenTimes(FIXED_GREEN_TIMES)
      return
    }

    // In AI mode, green times come from /api/mode and /ws/simulation snapshots,
    // which are backed by backend/services/ai rather than the legacy calculator.
  }, [])

  const configureStoppedSimulation = useCallback(async (nextMode, nextPeakHour, nextHeavyNorth) => {
    try {
      const state = await startSim({
        mode: nextMode,
        peak_hour: nextPeakHour,
        heavy_north: nextHeavyNorth,
        bus_directions: nextHeavyNorth ? ['north'] : [],
        reset: true,
        autostart: false,
      })
      applySnapshot(state)
      await syncSignalPlan(state.queues)
      setError('')
    } catch (err) {
      setApiError(err)
    }
  }, [applySnapshot, setApiError, syncSignalPlan])

  const setMode = useCallback((nextModeOrUpdater) => {
    const nextMode = readNextValue(nextModeOrUpdater, modeRef.current)
    setModeState(nextMode)
    modeRef.current = nextMode

    void (async () => {
      try {
        const state = await switchMode(nextMode)
        applySnapshot(state)
        setError('')
      } catch (err) {
        setApiError(err)
      }
    })()
  }, [applySnapshot, setApiError])

  const setPeakHour = useCallback((nextPeakOrUpdater) => {
    const nextPeak = readNextValue(nextPeakOrUpdater, peakHourRef.current)
    setPeakHourState(nextPeak)
    setIsRunningState(false)
    peakHourRef.current = nextPeak
    isRunningRef.current = false
    void configureStoppedSimulation(modeRef.current, nextPeak, heavyNorthRef.current)
  }, [configureStoppedSimulation])

  const setHeavyNorth = useCallback((nextHeavyOrUpdater) => {
    const nextHeavy = readNextValue(nextHeavyOrUpdater, heavyNorthRef.current)
    setHeavyNorthState(nextHeavy)
    setIsRunningState(false)
    heavyNorthRef.current = nextHeavy
    isRunningRef.current = false
    void configureStoppedSimulation(modeRef.current, peakHourRef.current, nextHeavy)
  }, [configureStoppedSimulation])

  const setIsRunning = useCallback((nextRunningOrUpdater) => {
    const nextRunning = Boolean(readNextValue(nextRunningOrUpdater, isRunningRef.current))
    setIsRunningState(nextRunning)
    isRunningRef.current = nextRunning

    if (nextRunning) {
      void (async () => {
        try {
          const state = await startSim({
            mode: modeRef.current,
            peak_hour: peakHourRef.current,
            heavy_north: heavyNorthRef.current,
            bus_directions: heavyNorthRef.current ? ['north'] : [],
            reset: false,
            autostart: true,
          })
          applySnapshot(state)
          setError('')
        } catch (err) {
          setIsRunningState(false)
          isRunningRef.current = false
          setApiError(err)
        }
      })()
      return
    }

    void (async () => {
      try {
        const state = await stopSim()
        applySnapshot(state)
        setError('')
      } catch (err) {
        setApiError(err)
      }
    })()
  }, [applySnapshot, setApiError])

  const setSpeed = useCallback((nextSpeedOrUpdater) => {
    const nextSpeed = Number(readNextValue(nextSpeedOrUpdater, speedRef.current))
    setSpeedState(nextSpeed)
    speedRef.current = nextSpeed

    void (async () => {
      try {
        const state = await setSpeedApi(nextSpeed)
        applySnapshot(state)
        setError('')
      } catch (err) {
        setApiError(err)
      }
    })()
  }, [applySnapshot, setApiError])

  const reset = useCallback(() => {
    setIsRunningState(false)
    isRunningRef.current = false
    void configureStoppedSimulation(modeRef.current, peakHourRef.current, heavyNorthRef.current)
  }, [configureStoppedSimulation])

  useEffect(() => {
    let cancelled = false

    const bootstrap = async () => {
      setIsLoading(true)
      try {
        const [state, comparison, queueHistory] = await Promise.all([
          getSimulationState(),
          getComparison(),
          getQueueHistory(),
        ])

        if (cancelled) return

        const mergedState = {
          ...state,
          avgFixedWait: comparison.avgFixedWait,
          avgAIWait: comparison.avgAIWait,
          history: queueHistory.history?.length ? queueHistory.history : state.history,
        }

        applySnapshot(mergedState)
        await syncSignalPlan(mergedState.queues)
        setError('')
      } catch (err) {
        if (!cancelled) {
          setApiError(err)
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false)
        }
      }
    }

    void bootstrap()
    return () => {
      cancelled = true
    }
  }, [applySnapshot, setApiError, syncSignalPlan])

  useEffect(() => {
    let disconnected = false
    let reconnectTimeout = null
    let teardown = () => {}

    const connect = () => {
      teardown = connectWebSocket(
        (snapshot) => {
          if (disconnected) return
          suppressSocketErrorRef.current = false
          applySnapshot(snapshot)
          setError('')
        },
        (socketError) => {
          if (disconnected || suppressSocketErrorRef.current) return
          setApiError(socketError, 'WebSocket connection lost')
          reconnectTimeout = setTimeout(connect, 1500)
        }
      )
    }

    connect()

    return () => {
      disconnected = true
      suppressSocketErrorRef.current = true
      if (reconnectTimeout) clearTimeout(reconnectTimeout)
      teardown()
    }
  }, [applySnapshot, setApiError])

  const result = useMemo(() => ({
    mode,
    setMode,
    peakHour,
    setPeakHour,
    heavyNorth,
    setHeavyNorth,
    isRunning,
    setIsRunning,
    speed,
    setSpeed,
    activeDir,
    phaseTimer,
    queues,
    totalPassed,
    waitTimes,
    vehicles,
    intersections,
    simTime,
    history,
    reset,
    avgFixedWait,
    avgAIWait,
    greenTimes,
    aiActivePhase,
    aiDecisionReason,
    aiCongestionState,
    antiGridlockActive,
    pedestrianWaiting,
    emergencyActive,
    neighborPressure,
    isLoading,
    error,
  }), [
    mode,
    setMode,
    peakHour,
    setPeakHour,
    heavyNorth,
    setHeavyNorth,
    isRunning,
    setIsRunning,
    speed,
    setSpeed,
    activeDir,
    phaseTimer,
    queues,
    totalPassed,
    waitTimes,
    vehicles,
    intersections,
    simTime,
    history,
    reset,
    avgFixedWait,
    avgAIWait,
    greenTimes,
    aiActivePhase,
    aiDecisionReason,
    aiCongestionState,
    antiGridlockActive,
    pedestrianWaiting,
    emergencyActive,
    neighborPressure,
    isLoading,
    error,
  ])

  return result
}

export { DIRECTIONS, INTERSECTION_POSITIONS }
