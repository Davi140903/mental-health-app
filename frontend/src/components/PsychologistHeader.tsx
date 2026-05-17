import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/useAuth';

type PsychologistHeaderProps = {
  eyebrow: string;
  title: string;
  description: string;
};

export default function PsychologistHeader({ eyebrow, title, description }: PsychologistHeaderProps) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <header className="psychologist-topbar">
      <div>
        <span className="role-pill">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{user?.nome ? `Profissional: ${user.nome}` : description}</p>
      </div>

      <div className="psychologist-top-actions" aria-label="Navegacao profissional">
        <Link
          to="/psicologo"
          className={location.pathname === '/psicologo' ? 'psychologist-nav-button primary' : 'psychologist-nav-button'}
        >
          Relatorios
        </Link>
        <Link
          to="/psicologo/agenda"
          className={
            location.pathname === '/psicologo/agenda' ? 'psychologist-nav-button primary' : 'psychologist-nav-button'
          }
        >
          Minha agenda
        </Link>
        <button type="button" className="psychologist-nav-button" onClick={handleLogout}>
          Sair
        </button>
      </div>
    </header>
  );
}
