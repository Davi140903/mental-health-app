import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { useAuth } from './contexts/useAuth';
import Dashboard from './pages/DashboardChat';
import GAD7 from './pages/GAD7';
import Humor from './pages/Humor';
import Login from './pages/Login';
import PHQ9 from './pages/PHQ9';
import Profile from './pages/Profile';
import Register from './pages/Register';
import Contents from './pages/Contents';

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { token, loading } = useAuth();

  if (loading) {
    return <div className="center-screen">Carregando ambiente...</div>;
  }

  return token ? <>{children}</> : <Navigate to="/login" replace />;
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
        path="/dashboard"
        element={
          <PrivateRoute>
            <Dashboard />
          </PrivateRoute>
        }
      />
      <Route
        path="/humor"
        element={
          <PrivateRoute>
            <Humor />
          </PrivateRoute>
        }
      />
      <Route
        path="/phq9"
        element={
          <PrivateRoute>
            <PHQ9 />
          </PrivateRoute>
        }
      />
      <Route
        path="/gad7"
        element={
          <PrivateRoute>
            <GAD7 />
          </PrivateRoute>
        }
      />
      <Route
        path="/contents"
        element={
          <PrivateRoute>
            <Contents />
          </PrivateRoute>
        }
      />
      <Route
        path="/profile"
        element={
          <PrivateRoute>
            <Profile />
          </PrivateRoute>
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
