/**
 * useTrafficSimulation.js
 * =======================
 * React hook: connects to the FastAPI WebSocket simulation stream.
 * Provides live intersection states to IntersectionCanvas and MetricsPanel.
 *
 * Usage:
 *   const { aiState, tradState, metrics, connected } = useTrafficSimulation();
 */

import { useState, useEffect, useRef, useCallback } from 'react';

const WS_URL = process.env.REACT_APP_WS_URL || 'ws://localhost:8000/ws/simulation';
const RECONNECT_DELAY_MS = 2000;
const MAX_METRICS_HISTORY = 120; // 2 minutes at 1 Hz

/**
 * @typedef {Object} IntersectionState
 * @property {number} id
 * @property {string} name
 * @property {{ N: string, S: string, E: string, W: string }} signals
 * @property {string} phase
 * @property {number} phase_elapsed
 * @property {number} phase_remaining
 * @property {{ avg_wait: number, queue: number, congestion_index: number }} metrics
 * @property {boolean} ai_mode
 * @property {string} ai_reason
 * @property {boolean} anti_gridlock
 * @property {{ N: number, S: number, E: number, W: number }} pedestrian
 * @property {boolean} emergency
 */

export function useTrafficSimulation() {
  const wsRef = useRef(null);
  const reconnectTimerRef = useRef(null);

  const [connected, setConnected] = useState(false);
  const [tick, setTick] = useState(0);
  const [weather, setWeather] = useState('Clear');

  /** @type {[Record<number, IntersectionState>, Function]} */
  const [aiState, setAiState] = useState({});
  /** @type {[Record<number, IntersectionState>, Function]} */
  const [tradState, setTradState] = useState({});

  /** Aggregate comparison metrics [{timestamp, ai, traditional}, ...] */
  const [metricsHistory, setMetricsHistory] = useState([]);

  /** Latest aggregate snapshot */
  const [aggregate, setAggregate] = useState(null);

  // ─── WebSocket connection ───────────────────

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      console.log('[TrafficSim] WS connected');
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type !== 'simulation_update') return;

        setTick(payload.tick);
        setWeather(payload.weather ?? 'Clear');

        // Intersection states
        if (payload.intersections?.ai) {
          setAiState(payload.intersections.ai);
        }
        if (payload.intersections?.traditional) {
          setTradState(payload.intersections.traditional);
        }

        // Aggregate metrics
        if (payload.aggregate) {
          setAggregate(payload.aggregate);
          setMetricsHistory(prev => {
            const next = [...prev, {
              tick: payload.tick,
              timestamp: payload.timestamp,
              ai_wait: payload.aggregate.ai?.avg_wait_sec ?? 0,
              ai_congestion: payload.aggregate.ai?.avg_congestion ?? 0,
              ai_queue: payload.aggregate.ai?.total_queue ?? 0,
              trad_wait: payload.aggregate.traditional?.avg_wait_sec ?? 0,
              trad_congestion: payload.aggregate.traditional?.avg_congestion ?? 0,
              trad_queue: payload.aggregate.traditional?.total_queue ?? 0,
            }];
            return next.slice(-MAX_METRICS_HISTORY);
          });
        }
      } catch (e) {
        console.warn('[TrafficSim] parse error', e);
      }
    };

    ws.onclose = () => {
      setConnected(false);
      console.log('[TrafficSim] WS closed, reconnecting...');
      reconnectTimerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
    };

    ws.onerror = (err) => {
      console.error('[TrafficSim] WS error', err);
      ws.close();
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  // ─── REST API helpers ────────────────────────

  const triggerEmergency = useCallback(async (intersectionId, direction = 'N') => {
    const base = process.env.REACT_APP_API_URL || 'http://localhost:8000';
    await fetch(`${base}/api/emergency/${intersectionId}?direction=${direction}`, {
      method: 'POST',
    });
  }, []);

  const updateWeatherAPI = useCallback(async (condition) => {
    const base = process.env.REACT_APP_API_URL || 'http://localhost:8000';
    await fetch(`${base}/api/weather`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ condition }),
    });
  }, []);

  const updatePedestrian = useCallback(async (intersectionId, crosswalkId, count) => {
    const base = process.env.REACT_APP_API_URL || 'http://localhost:8000';
    await fetch(`${base}/api/pedestrian`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        intersection_id: intersectionId,
        crosswalk_id: crosswalkId,
        waiting_count: count,
      }),
    });
  }, []);

  // ─── Derived metrics for UI ──────────────────

  const comparisonMetrics = aggregate
    ? {
        waitImprovement: aggregate.ai?.avg_wait_sec > 0
          ? Math.round((1 - aggregate.ai.avg_wait_sec / Math.max(aggregate.traditional?.avg_wait_sec, 1)) * 100)
          : 0,
        queueImprovement: aggregate.traditional?.total_queue > 0
          ? Math.round((1 - aggregate.ai.total_queue / aggregate.traditional.total_queue) * 100)
          : 0,
        congestionImprovement: aggregate.traditional?.avg_congestion > 0
          ? Math.round((1 - aggregate.ai.avg_congestion / aggregate.traditional.avg_congestion) * 100)
          : 0,
        emergencyActive: aggregate.ai?.emergency_active ?? false,
      }
    : null;

  return {
    // Connection state
    connected,
    tick,
    weather,

    // Intersection states (keyed by intersection ID 0-8)
    aiState,       // Record<number, IntersectionState>
    tradState,     // Record<number, IntersectionState>

    // Metrics
    aggregate,             // latest aggregate snapshot
    metricsHistory,        // time series for charts
    comparisonMetrics,     // derived improvement percentages

    // Actions
    triggerEmergency,
    updateWeatherAPI,
    updatePedestrian,
  };
}
