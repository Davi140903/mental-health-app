import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/useAuth';
import AppFooter from './AppFooter';

const links = [
  { to: '/painel', label: 'Painel' },
  { to: '/lia', label: 'Lia' },
  { to: '/humor', label: 'Humor' },
  { to: '/contents', label: 'Conteúdos' },
  { to: '/profile', label: 'Perfil' },
];

export default function Layout({
  children,
  immersive = false,
}: {
  children: React.ReactNode;
  immersive?: boolean;
}) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="app-shell">
      <header className={immersive ? 'topbar topbar-quiet' : 'topbar'}>
        <div className="topbar-brand">
          <h1>{immersive ? 'Lia' : 'Mental Health App'}</h1>
          <p>{user?.nome ? `Olá, ${user.nome}.` : 'Seu espaço de cuidado.'}</p>
        </div>

        <button type="button" className="secondary-button" onClick={handleLogout}>
          Sair
        </button>
      </header>

      <nav className={immersive ? 'nav-strip nav-strip-quiet' : 'nav-strip'} aria-label="Navegação principal">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
          >
            {link.label}
          </NavLink>
        ))}
      </nav>

      <main className={immersive ? 'page-container page-container-immersive' : 'page-container'}>{children}</main>
      <AppFooter tone="user" />
    </div>
  );
}
