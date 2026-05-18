import { useAuth } from '../contexts/useAuth';
import AppFooter from './AppFooter';
import AppHeader from './AppHeader';

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
  const { user } = useAuth();

  return (
    <div className="app-shell">
      <AppHeader
        brand="Lia"
        subtitle={user?.nome ? `Olá, ${user.nome}.` : 'Seu espaço de cuidado.'}
        links={links}
      />

      <main className={immersive ? 'page-container page-container-immersive' : 'page-container'}>{children}</main>
      <AppFooter tone="user" />
    </div>
  );
}
