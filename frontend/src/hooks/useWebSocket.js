import { useState, useEffect, useRef } from 'react';
import { authFetch } from '../services/auth';

export default function useWebSocket(url) {
  const [events, setEvents] = useState([]);
  const [health, setHealth] = useState({});
  const [alerts, setAlerts] = useState([]);
  const [metrics, setMetrics] = useState({});
  const [liveTracks, setLiveTracks] = useState({});
  const lastSequence = useRef({});

  useEffect(() => {
    // Fetch initial state so data isn't blank on tab switch
    authFetch('/events?limit=100').then(res => res.ok && res.json()).then(data => {
      if (Array.isArray(data)) setEvents(data);
    }).catch(e => console.error('Failed to fetch initial events:', e));

    authFetch('/alerts?limit=100').then(res => res.ok && res.json()).then(data => {
      if (Array.isArray(data)) setAlerts(data);
    }).catch(e => console.error('Failed to fetch initial alerts:', e));

    authFetch('/cameras').then(res => res.ok && res.json()).then(data => {
      if (Array.isArray(data)) {
        const hMap = {};
        data.forEach(c => { hMap[c.camera_id] = { health_state: c.health_state, camera_id: c.camera_id }; });
        setHealth(hMap);
      }
    }).catch(e => console.error('Failed to fetch initial health:', e));
    let ws = null;
    let reconnectTimer = null;
    let isMounted = true;
    let reconnectAttempts = 0;
    const MAX_RECONNECT_ATTEMPTS = 10;

    const connect = () => {
      ws = new WebSocket(url);

      ws.onopen = () => {
        reconnectAttempts = 0; // Reset on successful connection
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'new_event') {
            setEvents(prev => [data.payload, ...prev].slice(0, 100)); // Keep last 100
          } else if (data.type === 'camera_health') {
            setHealth(prev => ({ ...prev, [data.health.camera_id]: data.health }));
          } else if (data.type === 'new_alert') {
            setAlerts(prev => [data.alert, ...prev]);
          } else if (data.type === 'pipeline_metrics') {
            setMetrics(prev => ({ ...prev, [data.metrics.edge_device_id]: data.metrics }));
          } else if (data.type === 'live_telemetry') {
            const tel = data.telemetry;
            const cid = tel.camera_id;
            if (lastSequence.current[cid] && tel.sequence <= lastSequence.current[cid]) {
              return; // Out of order or duplicate
            }
            lastSequence.current[cid] = tel.sequence;
            setLiveTracks(prev => ({ ...prev, [cid]: { timestamp: Date.now(), tracks: tel.tracks } }));
          }
        } catch (err) {
          console.error("WebSocket parsing error", err);
        }
      };

      ws.onclose = () => {
        if (isMounted && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
          reconnectAttempts++;
          reconnectTimer = setTimeout(connect, delay);
        } else if (isMounted) {
          console.error("WebSocket reconnect limit reached. Server permanently unavailable.");
        }
      };
    };

    connect();

    return () => {
      isMounted = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) ws.close();
    };
  }, [url]);

  return { events, health, alerts, metrics, liveTracks };
}
