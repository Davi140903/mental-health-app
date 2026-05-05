import { createContext } from 'react';
import type { CodeRequestResponse, ProfileUpdate, Usuario, UsuarioCreate } from '../types/auth';

export interface AuthContextValue {
  user: Usuario | null;
  token: string | null;
  loading: boolean;
  requestRegisterCode: (email: string) => Promise<CodeRequestResponse>;
  requestLoginCode: (email: string, password: string) => Promise<CodeRequestResponse>;
  login: (email: string, password: string, codigo: string) => Promise<void>;
  register: (data: UsuarioCreate) => Promise<void>;
  refreshUser: () => Promise<Usuario>;
  updateProfile: (data: ProfileUpdate) => Promise<Usuario>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
