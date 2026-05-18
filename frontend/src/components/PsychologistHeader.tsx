import { useAuth } from '../contexts/useAuth';
import AppHeader from './AppHeader';

type PsychologistHeaderProps = {
  eyebrow: string;
  title: string;
  description: string;
};

export default function PsychologistHeader({ eyebrow, title, description }: PsychologistHeaderProps) {
  const { user } = useAuth();

  return (
    <>
      <AppHeader
        tone="psychologist"
        brand="Lia"
        subtitle={user?.nome ? `Profissional: ${user.nome}` : 'Área profissional'}
        links={[
          { to: '/psicologo', label: 'Relatórios' },
          { to: '/psicologo/agenda', label: 'Minha agenda' },
        ]}
      />
      <div className="professional-page-heading">
        <span className="role-pill">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
    </>
  );
}
