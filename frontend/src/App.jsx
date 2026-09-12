import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Header from './components/Header';
import DemoSidebar from './components/DemoSidebar';
import { DemoScenarioProvider } from './hooks/useDemoScenario';
import ProtectedRoute from './components/ProtectedRoute';

import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Evidence from './pages/Evidence';
import Health from './pages/Health';
import Architecture from './pages/Architecture';
import Alerts from './pages/Alerts';
import Performance from './pages/Performance';
import CameraManagement from './pages/CameraManagement';

function AppLayout() {
  return (
    <div className="app-container">
      <Sidebar />
      <Header />

      <main className="main-content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/camera-health" element={<Health />} />
          <Route path="/evidence" element={<Evidence />} />
          <Route path="/cross-command-alerts" element={<Alerts />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/camera-management" element={<CameraManagement />} />
          <Route path="/architecture" element={<Architecture />} />
        </Routes>
      </main>

      <DemoSidebar />
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <DemoScenarioProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                <AppLayout />
              </ProtectedRoute>
            }
          />
        </Routes>
      </DemoScenarioProvider>
    </BrowserRouter>
  );
}

export default App;
