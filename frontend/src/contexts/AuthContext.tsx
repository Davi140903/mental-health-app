import { startTransition, useEffect, useState } from 'react';
import { authService } from '../services/auth';
import { AuthContext } from './auth-context';
import type { ProfileUpdate, Usuario, UsuarioCreate } from '../types/auth';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Usuario | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('access_token'));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    const loadUser = async () => {
      if (!token) {
        if (active) {
          setLoading(false);
        }
        return;
      }

      try {
        const currentUser = await authService.getMe();
        if (!active) {
          return;
        }
        startTransition(() => {
          setUser(currentUser);
        });
      } catch {
        if (!active) {
          return;
        }
        localStorage.removeItem('access_token');
        setToken(null);
        setUser(null);
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    void loadUser();

    return () => {
      active = false;
    };
  }, [token]);

  const login = async (email: string, password: string) => {
    setLoading(true);
    try {
      const response = await authService.login({ email, password });
      localStorage.setItem('access_token', response.access_token);
      setToken(response.access_token);
      const currentUser = await authService.getMe();
      startTransition(() => {
        setUser(currentUser);
      });
    } finally {
      setLoading(false);
    }
  };

  const register = async (data: UsuarioCreate) => {
    setLoading(true);
    try {
      await authService.register(data);
      await login(data.email, data.password);
    } finally {
      setLoading(false);
    }
  };

  const refreshUser = async () => {
    const currentUser = await authService.getMe();
    startTransition(() => {
      setUser(currentUser);
    });
    return currentUser;
  };

  const updateProfile = async (data: ProfileUpdate) => {
    const updatedUser = await authService.updateProfile(data);
    startTransition(() => {
      setUser(updatedUser);
    });
    return updatedUser;
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    setToken(null);
    setUser(null);
    setLoading(false);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        loading,
        login,
        register,
        refreshUser,
        updateProfile,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
