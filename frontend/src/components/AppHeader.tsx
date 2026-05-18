import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/useAuth';

type HeaderLink = {
  to: string;
  label: string;
};

type AppHeaderProps = {
  tone?: 'user' | 'psychologist' | 'admin';
  brand: string;
  subtitle: string;
  links: HeaderLink[];
};

export default function AppHeader({ tone = 'user', brand, subtitle, links }: AppHeaderProps) {
  const { logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <header className={`site-header site-header-${tone}`}>
      <div className="site-header-inner">
        <div className="site-brand">
          <strong>{brand}</strong>
          <span>{subtitle}</span>
        </div>

        <nav className="site-nav" aria-label="Navegacao principal">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) => (isActive ? 'site-nav-link active' : 'site-nav-link')}
            >
              {link.label}
            </NavLink>
          ))}
        </nav>

        <button type="button" className="site-logout" onClick={handleLogout}>
          Sair
        </button>
      </div>
    </header>
  );
}
