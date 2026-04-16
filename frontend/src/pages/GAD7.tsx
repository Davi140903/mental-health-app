import QuestionnairePage from './QuestionnairePage';

const questions = [
  'Sentir-se nervoso, ansioso ou muito tenso.',
  'Nao conseguir parar ou controlar as preocupacoes.',
  'Preocupar-se demais com diversas coisas.',
  'Dificuldade para relaxar.',
  'Ficar tao inquieto que e dificil permanecer parado.',
  'Ficar facilmente irritado ou incomodado.',
  'Sentir medo como se algo ruim fosse acontecer.',
];

export default function GAD7() {
  return (
    <QuestionnairePage
      kind="gad7"
      title="Ansiedade nas ultimas semanas"
      description="Responda pensando nas ultimas duas semanas."
      questions={questions}
    />
  );
}
