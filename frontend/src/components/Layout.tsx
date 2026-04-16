import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/useAuth';

const links = [
  { to: '/dashboard', label: 'Lia' },
  { to: '/humor', label: 'Humor' },
  { to: '/contents', label: 'Conteudos' },
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
          <p>{user?.nome ? `Ola, ${user.nome}.` : 'Seu espaco de cuidado.'}</p>
        </div>

        <button type="button" className="secondary-button" onClick={handleLogout}>
          Sair
        </button>
      </header>

      {!immersive ? (
        <nav className="nav-strip" aria-label="Navegacao principal">
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
      ) : null}

      <main className={immersive ? 'page-container page-container-immersive' : 'page-container'}>{children}</main>
    </div>
  );
}
