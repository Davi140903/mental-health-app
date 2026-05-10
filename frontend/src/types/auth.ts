export interface Usuario {
  id: string;
  email: string;
  nome: string;
  role: 'user' | 'psychologist' | 'admin';
  consentimento_lgpd: boolean;
  criado_em: string;
}

export interface UsuarioCreate {
  email: string;
  nome: string;
  password: string;
  consentimento_lgpd: boolean;
  codigo: string;
}

export interface ProfileUpdate {
  nome: string;
  consentimento_lgpd: boolean;
}

export interface LoginData {
  email: string;
  password: string;
  codigo: string;
}

export interface EmailCodeRequest {
  email: string;
}

export interface LoginCodeRequest {
  email: string;
  password: string;
}

export interface PasswordResetConfirm {
  email: string;
  codigo: string;
  nova_senha: string;
}

export interface CodeRequestResponse {
  detail: string;
  expires_in_minutes: number;
  debug_code: string | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
}
