import { useState, useEffect } from 'react';

export default function useWebSocket(url) {
  const [events, setEvents] = useState([]);
  const [health, setHealth] = useState({});
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    const ws = new WebSocket(url);
    
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'new_event') {
          setEvents(prev => [data.payload, ...prev].slice(0, 100)); // Keep last 100
        } else if (data.type === 'camera_health') {
          setHealth(prev => ({ ...prev, [data.health.camera_id]: data.health }));
        } else if (data.type === 'new_alert') {
          setAlerts(prev => [data.alert, ...prev]);
        }
      } catch (err) {
        console.error("WebSocket parsing error", err);
      }
    };

    return () => {
      ws.close();
    };
  }, [url]);

  return { events, health, alerts };
}
