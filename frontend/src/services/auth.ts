import api from './api';
import type { AuthResponse, LoginData, ProfileUpdate, Usuario, UsuarioCreate } from '../types/auth';
import type { ExportData } from '../types/app';

export const authService = {
  async login(data: LoginData): Promise<AuthResponse> {
    const response = await api.post<AuthResponse>('/auth/login', data);
    return response.data;
  },

  async register(data: UsuarioCreate): Promise<Usuario> {
    const response = await api.post<Usuario>('/auth/register', data);
    return response.data;
  },

  async getMe(): Promise<Usuario> {
    const response = await api.get<Usuario>('/auth/me');
    return response.data;
  },

  async updateProfile(data: ProfileUpdate): Promise<Usuario> {
    const response = await api.patch<Usuario>('/profile', data);
    return response.data;
  },

  async exportData(): Promise<ExportData> {
    const response = await api.get<ExportData>('/profile/export');
    return response.data;
  },

  async deleteProfile(): Promise<void> {
    await api.delete('/profile');
  },
};
