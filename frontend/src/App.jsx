import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import DemoSidebar from './components/DemoSidebar';

import Dashboard from './pages/Dashboard';
import Evidence from './pages/Evidence';
import Health from './pages/Health';
import Architecture from './pages/Architecture';
import Alerts from './pages/Alerts';

function App() {
  return (
    <BrowserRouter>
      <div className="app-container">
        <Sidebar />
        <Header />
        
        <main className="main-content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/camera-health" element={<Health />} />
            <Route path="/evidence" element={<Evidence />} />
            {/* Not "/alerts" — that collides with the real backend route
                GET /alerts (backend/api/alerts.py), same class of bug as
                the earlier /health collision (see docs/LIMITATIONS.md).
                A direct hard-navigation to /alerts hit the backend's JSON
                instead of this page; in-app <Link> navigation masked it
                because that's client-side routing, never a real request. */}
            <Route path="/cross-command-alerts" element={<Alerts />} />
            <Route path="/architecture" element={<Architecture />} />
          </Routes>
        </main>
        
        <DemoSidebar />
      </div>
    </BrowserRouter>
  );
}

export default App;
