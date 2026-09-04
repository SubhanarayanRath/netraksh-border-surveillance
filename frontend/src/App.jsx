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
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/architecture" element={<Architecture />} />
          </Routes>
        </main>
        
        <DemoSidebar />
      </div>
    </BrowserRouter>
  );
}

export default App;
