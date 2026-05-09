const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

const toWsBase = (httpBase) => {
  if (httpBase.startsWith('https://')) {
    return httpBase.replace('https://', 'wss://')
  }
  return httpBase.replace('http://', 'ws://')
}

const getErrorMessage = async (response) => {
  try {
    const payload = await response.json()
    if (typeof payload?.detail === 'string') return payload.detail
    if (Array.isArray(payload?.detail) && payload.detail[0]?.msg) return payload.detail[0].msg
  } catch (_) {
    // Ignore JSON parsing errors and fallback to generic status text.
  }
  return `${response.status} ${response.statusText}`
}

const request = async (path, options = {}) => {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })

  if (!response.ok) {
    const message = await getErrorMessage(response)
    throw new Error(message || 'Request failed')
  }

  if (response.status === 204) return null
  return response.json()
}

export const calculateSignal = async (data) => request('/api/signals/calculate', {
  method: 'POST',
  body: JSON.stringify(data),
})

export const startSim = async (payload = {}) => request('/api/simulation/start', {
  method: 'POST',
  body: JSON.stringify(payload),
})

export const stopSim = async () => request('/api/simulation/stop', {
  method: 'POST',
})

export const setSpeed = async (multiplier) => request('/api/simulation/speed', {
  method: 'POST',
  body: JSON.stringify({ multiplier }),
})

export const switchMode = async (mode) => request('/api/mode', {
  method: 'POST',
  body: JSON.stringify({ mode }),
})

export const getSimulationState = async () => request('/api/simulation/state')

export const getComparison = async () => request('/api/analytics/comparison')

export const getQueueHistory = async () => request('/api/analytics/queue-history')

export const connectWebSocket = (onMessage, onError) => {
  const ws = new WebSocket(`${toWsBase(API_BASE_URL)}/ws/simulation`)

  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data)
      onMessage(payload)
    } catch (error) {
      if (onError) onError(error)
    }
  }

  ws.onerror = () => {
    if (onError) onError(new Error('WebSocket connection failed'))
  }

  ws.onclose = () => {
    if (onError) onError(new Error('WebSocket disconnected'))
  }

  return () => {
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
      ws.close()
    }
  }
}
