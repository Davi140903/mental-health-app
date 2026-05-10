import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { useAuth } from './contexts/useAuth';
import AdminDashboard from './pages/AdminDashboard';
import Dashboard from './pages/Dashboard';
import GAD7 from './pages/GAD7';
import Humor from './pages/Humor';
import Login from './pages/Login';
import Panel from './pages/Panel';
import RecoverLogin from './pages/RecoverLogin';
import PHQ9 from './pages/PHQ9';
import Profile from './pages/Profile';
import PsychologistDashboard from './pages/PsychologistDashboard';
import Register from './pages/Register';
import Contents from './pages/Contents';
import DashboardChat from './pages/DashboardChat';
import { hasActiveCheckInCooldown } from './utils/checkin';
import type { Usuario } from './types/auth';

function roleHome(user?: Usuario | null) {
  if (user?.role === 'admin') {
    return '/admin';
  }

  if (user?.role === 'psychologist') {
    return '/psicologo';
  }

  return '/dashboard';
}

function CheckInRoute({ children }: { children: React.ReactNode }) {
  const { token, user, loading } = useAuth();

  if (loading) {
    return <div className="center-screen">Carregando ambiente...</div>;
  }

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  if (user?.role !== 'user') {
    return <Navigate to={roleHome(user)} replace />;
  }

  if (user && !hasActiveCheckInCooldown(user.id)) {
    return <Navigate to="/dashboard" replace />;
  }

  return <>{children}</>;
}

function PublicRoute({ children }: { children: React.ReactNode }) {
  const { token, user, loading } = useAuth();

  if (loading) {
    return <div className="center-screen">Carregando ambiente...</div>;
  }

  return token ? <Navigate to={roleHome(user)} replace /> : <>{children}</>;
}

function UserRoute({ children }: { children: React.ReactNode }) {
  const { token, user, loading } = useAuth();

  if (loading) {
    return <div className="center-screen">Carregando ambiente...</div>;
  }

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  return user?.role === 'user' ? <>{children}</> : <Navigate to={roleHome(user)} replace />;
}

function RoleRoute({
  children,
  allowedRoles,
}: {
  children: React.ReactNode;
  allowedRoles: Usuario['role'][];
}) {
  const { token, user, loading } = useAuth();

  if (loading) {
    return <div className="center-screen">Carregando ambiente...</div>;
  }

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  return user && allowedRoles.includes(user.role) ? <>{children}</> : <Navigate to={roleHome(user)} replace />;
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
          <UserRoute>
            <Dashboard />
          </UserRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <RoleRoute allowedRoles={['admin']}>
            <AdminDashboard />
          </RoleRoute>
        }
      />
      <Route
        path="/psicologo"
        element={
          <RoleRoute allowedRoles={['psychologist', 'admin']}>
            <PsychologistDashboard />
          </RoleRoute>
        }
      />
      <Route
        path="/painel"
        element={
          <CheckInRoute>
            <Panel />
          </CheckInRoute>
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
