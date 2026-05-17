type AppFooterProps = {
  tone?: 'user' | 'psychologist' | 'admin';
};

export default function AppFooter({ tone = 'user' }: AppFooterProps) {
  return (
    <footer className={`app-footer app-footer-${tone}`}>
      <strong>Lia</strong>
      <span>Apoio, bem-estar e triagem. Este sistema nao substitui atendimento profissional.</span>
    </footer>
  );
}
