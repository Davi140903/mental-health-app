import { useEffect, useState } from 'react';
import AppFooter from '../components/AppFooter';
import PsychologistHeader from '../components/PsychologistHeader';
import { appService } from '../services/app';
import type { TriageSlot } from '../types/app';

const agendaHours = ['08:00', '09:00', '10:00', '11:00', '14:00', '15:00', '16:00', '17:00'];

function formatDateTime(value?: string | null) {
  if (!value) {
    return 'Sem horário definido';
  }

  return new Intl.DateTimeFormat('pt-BR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

function toDatetimeLocalValue(date = new Date(Date.now() + 24 * 60 * 60 * 1000)) {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return shifted.toISOString().slice(0, 16);
}

function toDateInputValue(date = new Date(Date.now() + 24 * 60 * 60 * 1000)) {
  return toDatetimeLocalValue(date).slice(0, 10);
}

function combineDateAndHour(dateValue: string, hourValue: string) {
  return new Date(`${dateValue}T${hourValue}:00`);
}

export default function PsychologistAgenda() {
  const [slots, setSlots] = useState<TriageSlot[]>([]);
  const [agendaDate, setAgendaDate] = useState(toDateInputValue());
  const [slotFeedback, setSlotFeedback] = useState('');
  const [slotBusy, setSlotBusy] = useState(false);

  useEffect(() => {
    let active = true;

    const loadSlots = async () => {
      try {
        const response = await appService.listPsychologistSlots();
        if (active) {
          setSlots(response);
        }
      } catch {
        if (active) {
          setSlotFeedback('Não foi possível carregar sua agenda agora.');
        }
      }
    };

    void loadSlots();

    return () => {
      active = false;
    };
  }, []);

  const handleCreateSlotAt = async (hour: string) => {
    setSlotBusy(true);
    setSlotFeedback('');
    try {
      const created = await appService.createPsychologistSlot(combineDateAndHour(agendaDate, hour).toISOString());
      setSlots((current) =>
        [...current.filter((slot) => slot.id !== created.id), created].sort(
          (a, b) => new Date(a.starts_at).getTime() - new Date(b.starts_at).getTime(),
        ),
      );
      setSlotFeedback(`Horário de ${hour} publicado para os pacientes.`);
    } catch {
      setSlotFeedback('Não foi possível criar esse horário.');
    } finally {
      setSlotBusy(false);
    }
  };

  const handleDeleteSlot = async (slotId: number) => {
    setSlotBusy(true);
    setSlotFeedback('');
    try {
      await appService.deletePsychologistSlot(slotId);
      setSlots((current) => current.filter((slot) => slot.id !== slotId));
      setSlotFeedback('Horário removido da agenda.');
    } catch {
      setSlotFeedback('Não foi possível remover esse horário.');
    } finally {
      setSlotBusy(false);
    }
  };

  const selectedDateSlots = slots.filter((slot) => toDateInputValue(new Date(slot.starts_at)) === agendaDate);
  const findSlotAtHour = (hour: string) =>
    selectedDateSlots.find((slot) => toDatetimeLocalValue(new Date(slot.starts_at)).slice(11, 16) === hour);

  return (
    <div className="psychologist-app-shell">
      <PsychologistHeader
        eyebrow="Agenda profissional"
        title="Minha agenda"
        description="Defina os horários disponíveis para triagem."
      />

      <main className="psychologist-page">
        <section className="psychologist-workspace agenda-panel">
          <div className="psychologist-toolbar">
            <div>
              <h2>Horários disponíveis</h2>
              <p>Escolha uma data e publique os horários que os pacientes poderão selecionar ao finalizar a triagem.</p>
            </div>
          </div>

          <div className="agenda-create-row">
            <label>
              Data da agenda
              <input type="date" value={agendaDate} onChange={(event) => setAgendaDate(event.target.value)} />
            </label>
            <p>Cada horário usa a duração padrão da triagem. Clique em um horário vazio para publicar, ou em um disponível para remover.</p>
          </div>

          {slotFeedback ? <div className="alert success">{slotFeedback}</div> : null}

          <div className="agenda-calendar-grid">
            {agendaHours.map((hour) => {
              const slot = findSlotAtHour(hour);
              return (
                <button
                  key={hour}
                  type="button"
                  className={`agenda-hour-card ${slot ? (slot.available ? 'available' : 'busy') : ''}`}
                  onClick={() => (slot?.available ? void handleDeleteSlot(slot.id) : !slot ? void handleCreateSlotAt(hour) : undefined)}
                  disabled={slotBusy || Boolean(slot && !slot.available)}
                >
                  <strong>{hour}</strong>
                  <span>{slot ? (slot.available ? 'Disponível, clique para remover' : 'Agendado') : 'Livre para publicar'}</span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="psychologist-workspace">
          <div className="psychologist-toolbar">
            <div>
              <h2>Próximos horários publicados</h2>
              <p>Resumo rápido da agenda futura.</p>
            </div>
          </div>

          <div className="agenda-slot-list">
            {slots.length ? (
              slots.slice(0, 12).map((slot) => (
                <article key={slot.id} className={`agenda-slot-card ${slot.available ? '' : 'busy'}`}>
                  <div>
                    <strong>{formatDateTime(slot.starts_at)}</strong>
                    <span>{slot.available ? 'Disponível para pacientes' : 'Horário já agendado'}</span>
                  </div>
                </article>
              ))
            ) : (
              <div className="empty-state">Nenhum horário futuro cadastrado ainda.</div>
            )}
          </div>
        </section>
      </main>
      <AppFooter tone="psychologist" />
    </div>
  );
}
