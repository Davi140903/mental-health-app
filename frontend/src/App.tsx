import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { useAuth } from './contexts/useAuth';
import Dashboard from './pages/Dashboard';
import GAD7 from './pages/GAD7';
import Humor from './pages/Humor';
import Login from './pages/Login';
import RecoverLogin from './pages/RecoverLogin';
import PHQ9 from './pages/PHQ9';
import Profile from './pages/Profile';
import Register from './pages/Register';
import Contents from './pages/Contents';
import DashboardChat from './pages/DashboardChat';
import { hasActiveCheckInCooldown } from './utils/checkin';

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { token, loading } = useAuth();

  if (loading) {
    return <div className="center-screen">Carregando ambiente...</div>;
  }

  return token ? <>{children}</> : <Navigate to="/login" replace />;
}

function CheckInRoute({ children }: { children: React.ReactNode }) {
  const { token, user, loading } = useAuth();

  if (loading) {
    return <div className="center-screen">Carregando ambiente...</div>;
  }

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  if (user && !hasActiveCheckInCooldown(user.id)) {
    return <Navigate to="/dashboard" replace />;
  }

  return <>{children}</>;
}

function PublicRoute({ children }: { children: React.ReactNode }) {
  const { token, loading } = useAuth();

  if (loading) {
    return <div className="center-screen">Carregando ambiente...</div>;
  }

  return token ? <Navigate to="/dashboard" replace /> : <>{children}</>;
}

function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicRoute>
            <Login />
          </PublicRoute>
        }
      />
      <Route
        path="/register"
        element={
          <PublicRoute>
            <Register />
          </PublicRoute>
        }
      />
      <Route
        path="/recover"
        element={
          <PublicRoute>
            <RecoverLogin />
          </PublicRoute>
        }
      />
      <Route
        path="/dashboard"
        element={
          <PrivateRoute>
            <Dashboard />
          </PrivateRoute>
        }
      />
      <Route
        path="/lia"
        element={
          <CheckInRoute>
            <DashboardChat />
          </CheckInRoute>
        }
      />
      <Route
        path="/humor"
        element={
          <CheckInRoute>
            <Humor />
          </CheckInRoute>
        }
      />
      <Route
        path="/phq9"
        element={
          <CheckInRoute>
            <PHQ9 />
          </CheckInRoute>
        }
      />
      <Route
        path="/gad7"
        element={
          <CheckInRoute>
            <GAD7 />
          </CheckInRoute>
        }
      />
      <Route
        path="/contents"
        element={
          <CheckInRoute>
            <Contents />
          </CheckInRoute>
        }
      />
      <Route
        path="/profile"
        element={
          <CheckInRoute>
            <Profile />
          </CheckInRoute>
        }
      />
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
