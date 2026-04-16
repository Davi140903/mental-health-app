export interface Usuario {
  id: string;
  email: string;
  nome: string;
  consentimento_lgpd: boolean;
  criado_em: string;
}

export interface UsuarioCreate {
  email: string;
  nome: string;
  password: string;
  consentimento_lgpd: boolean;
}

export interface ProfileUpdate {
  nome: string;
  consentimento_lgpd: boolean;
}

export interface LoginData {
  email: string;
  password: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
}
