import QuestionnairePage from './QuestionnairePage';

const questions = [
  'Pouco interesse ou prazer em fazer as coisas.',
  'Sentir-se para baixo, deprimido ou sem esperanca.',
  'Dificuldade para pegar no sono, continuar dormindo ou dormir demais.',
  'Sentir-se cansado ou com pouca energia.',
  'Falta de apetite ou comer demais.',
  'Sentir-se mal consigo mesmo ou achar que decepcionou as pessoas.',
  'Dificuldade para se concentrar em leitura, estudo ou outras atividades.',
  'Mover-se ou falar muito devagar, ou se sentir inquieto demais.',
  'Pensar que seria melhor estar morto ou que poderia se ferir de alguma forma.',
];

export default function PHQ9() {
  return (
    <QuestionnairePage
      kind="phq9"
      title="Humor nas ultimas semanas"
      description="Responda pensando nas ultimas duas semanas."
      questions={questions}
    />
  );
}
