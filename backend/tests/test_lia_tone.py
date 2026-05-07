import unittest
from datetime import datetime, timezone

import main
from app.models import LiaInteraction
from app.schemas import LiaMemorySnapshot, LiaSessionState


class LiaToneTests(unittest.TestCase):
    def build_session(self, *, turn_count: int = 1, stage: str = "support") -> LiaSessionState:
        return LiaSessionState(
            stage=stage,
            turn_count=turn_count,
            clarification_streak=0,
            transcript=[],
            gad7_scores=[None] * 7,
            phq9_scores=[None] * 9,
            mood_value=None,
            focus_kind=None,
            completed=False,
            saved_questionnaires=[],
            saved_mood=False,
            memory=LiaMemorySnapshot(),
        )

    def test_first_contact_messages_sound_natural(self) -> None:
        user = main.User(nome="Davi", email="davi@example.com", hashed_password="x")
        messages = main.build_lia_welcome_messages(user, LiaMemorySnapshot())
        contents = [item.content for item in messages]

        self.assertIn("Me conta, como voce ta hoje?", contents)
        self.assertNotIn("Esse pode ser nosso primeiro cuidado por aqui. Nao precisa acertar as palavras.", contents)

    def test_fallback_reply_avoids_therapeutic_old_style(self) -> None:
        session = self.build_session()
        analysis = main.fallback_lia_analysis(session, "nao estou me sentindo muito bem")

        lowered = main.normalize_for_match(analysis.assistant_reply or "")
        self.assertNotIn("sinto muito que esteja assim", lowered)
        self.assertNotIn("na sua mente ou no seu corpo", lowered)
        self.assertIn("o que mais te pegou", lowered)

    def test_rejects_overly_therapeutic_reply_in_refinement(self) -> None:
        session = self.build_session()
        session.transcript = [main.LiaTranscriptMessage(role="assistant", content="Oi.")]
        analysis = main.LiaAnalysis(
            assistant_reply="Sinto muito que esteja assim. Isso pesa mais na sua mente ou no seu corpo?",
            reflection="teste",
            next_question=None,
            risk_level="none",
            mood_value=None,
            gad7_scores=[None] * 7,
            phq9_scores=[None] * 9,
            ready_to_close=False,
            recommended_stage="support",
        )

        with self.assertRaisesRegex(ValueError, "overly therapeutic"):
            main.refine_lia_analysis(session, analysis, "nao estou me sentindo muito bem")

    def test_unsure_reply_offers_positive_suggestions(self) -> None:
        session = self.build_session(stage="anxiety", turn_count=3)
        analysis = main.fallback_lia_analysis(session, "nao sei dizer")

        lowered = main.normalize_for_match(analysis.assistant_reply or "")
        self.assertIn("tudo bem", lowered)
        self.assertIn("cabeca cheia", lowered)
        self.assertIn("pressao por critica", lowered)

    def test_unsure_message_can_offer_pause_once(self) -> None:
        session = self.build_session(stage="support", turn_count=2)
        context = main.build_lia_context(session, "nao sei dizer")

        self.assertTrue(main.should_offer_pause(session, context))
        self.assertIn("quer", main.normalize_for_match(main.build_pause_offer_reply(session)))

        session.pause_offer_pending = True
        yes_context = main.build_lia_context(session, "sim")
        self.assertTrue(main.is_affirmative_pause_reply(yes_context))
        self.assertIn("ultima coisa pequena", main.normalize_for_match(main.build_pause_message(session)))

    def test_pause_can_use_light_prompt_topic(self) -> None:
        session = self.build_session(stage="support", turn_count=2)
        session.memory.light_prompt_value = "musica"

        lowered = main.normalize_for_match(main.build_pause_message(session))
        self.assertIn("musica", lowered)
        self.assertIn("voce tinha escolhido", lowered)

    def test_pause_offer_mentions_saved_topic(self) -> None:
        session = self.build_session(stage="support", turn_count=2)
        session.memory.light_prompt_value = "filmes e series"

        lowered = main.normalize_for_match(main.build_pause_offer_reply(session))
        self.assertIn("filmes e series", lowered)
        self.assertIn("anime", lowered)

    def test_post_pause_reply_can_acknowledge_topic(self) -> None:
        session = self.build_session(stage="support", turn_count=3)
        session.pause_used = True
        session.memory.light_prompt_value = "filmes e series"
        session.transcript = [
            main.LiaTranscriptMessage(
                role="assistant",
                content="Voce tinha escolhido filmes e series. O que te prende mais facil nisso: anime, suspense, comedia ou outra coisa?",
            )
        ]

        analysis = main.fallback_lia_analysis(session, "gosto de assistir animes")
        lowered = main.normalize_for_match(analysis.assistant_reply or "")
        self.assertIn("anime", lowered)
        self.assertIn("voltar para o que estava pesando", lowered)

    def test_interaction_summary_and_report_keep_simple_context(self) -> None:
        session = self.build_session(stage="support", turn_count=4)
        session.memory.light_prompt_value = "musica"
        session.transcript = [
            main.LiaTranscriptMessage(role="assistant", content="Oi."),
            main.LiaTranscriptMessage(role="user", content="estou cansado e me sentindo cobrado"),
            main.LiaTranscriptMessage(role="assistant", content="entendi"),
            main.LiaTranscriptMessage(role="user", content="isso esta pegando no trabalho"),
        ]
        session.gad7_scores[0] = 2
        session.phq9_scores[3] = 2
        session.pause_used = True

        topics = main.derive_memory_topics(session)
        summary = main.build_interaction_summary(session, topics)
        report = main.build_psychologist_report(session, topics)

        self.assertIn("musica", summary)
        self.assertIn("trabalho", report)
        self.assertIn("pausa leve", report)

    def test_memory_snapshot_can_include_recent_interactions(self) -> None:
        interaction = LiaInteraction(
            usuario_id="user-1",
            opening_label="Uma curiosidade pra comecar",
            opening_value="musica",
            summary="partimos de musica e o tema mais forte da conversa foi energia",
            report="Abertura do dia: musica.",
            topics=["energia"],
            mood_value=3,
            created_at=datetime.now(timezone.utc),
        )

        snapshot = main.build_lia_memory_snapshot(None, [interaction])

        self.assertEqual(len(snapshot.recent_conversations), 1)
        self.assertEqual(snapshot.latest_report, "Abertura do dia: musica.")

    def test_support_reply_does_not_stop_after_work_context(self) -> None:
        session = self.build_session(stage="support", turn_count=2)
        analysis = main.fallback_lia_analysis(session, "acho que muito trabalho")

        self.assertIsNotNone(analysis.assistant_reply)
        self.assertIn("?", analysis.assistant_reply or "")
        self.assertFalse(analysis.ready_to_close)

    def test_session_only_closes_with_enough_context(self) -> None:
        session = self.build_session(stage="anxiety", turn_count=4)
        session.transcript = [
            main.LiaTranscriptMessage(role="user", content="estou cansado"),
            main.LiaTranscriptMessage(role="user", content="acho que muito trabalho"),
        ]
        analysis = main.LiaAnalysis(
            assistant_reply="Entendi. O que mais pesou nisso?",
            reflection="Entendi.",
            next_question="O que mais pesou nisso?",
            risk_level="none",
            mood_value=2,
            gad7_scores=[2, None, None, None, None, None, None],
            phq9_scores=[None] * 9,
            ready_to_close=True,
            recommended_stage="anxiety",
        )

        self.assertFalse(main.should_close_lia_session(session, analysis, "anxiety", enough_distress_data=True))

    def test_energy_question_does_not_repeat_identically(self) -> None:
        session = self.build_session(stage="mood", turn_count=3)
        session.transcript = [
            main.LiaTranscriptMessage(
                role="assistant",
                content="Entendi. Quando o cansaco acumula, ate falar disso ja pode parecer muito. Junto com esse cansaco, voce percebeu menos vontade de fazer as coisas?",
            )
        ]

        next_question = main.build_contextual_question(session, "acho que muito trabalho", "mood")

        self.assertIsNotNone(next_question)
        self.assertNotEqual(
            next_question,
            "Junto com esse cansaco, voce percebeu menos vontade de fazer as coisas?",
        )

    def test_topic_states_progress_with_user_messages(self) -> None:
        session = self.build_session(stage="support", turn_count=0)

        main.infer_topic_states(session, "estou cansado com muito trabalho")
        main.infer_topic_states(session, "isso mexe no meu sono e na minha energia")
        main.infer_topic_states(session, "ja vem acontecendo na maior parte dos dias")

        self.assertTrue(session.topic_states["main_focus"].filled)
        self.assertTrue(session.topic_states["functional_impact"].filled)
        self.assertTrue(session.topic_states["frequency_duration"].filled)

    def test_next_lia_topic_moves_forward(self) -> None:
        session = self.build_session(stage="support", turn_count=0)
        main.update_topic_state(session, "opening_state", "cansado")
        main.update_topic_state(session, "main_focus", "trabalho")

        self.assertEqual(main.next_lia_topic(session), "distress_nature")

    def test_varia_bastante_fills_frequency_and_advances(self) -> None:
        session = self.build_session(stage="anxiety", turn_count=5)
        session.current_topic = "frequency_duration"
        session.transcript = [
            main.LiaTranscriptMessage(role="assistant", content="Oi, Davi. Eu sou a Lia."),
            main.LiaTranscriptMessage(role="user", content="Estou meio cansado."),
            main.LiaTranscriptMessage(
                role="assistant",
                content="Entendi. Junto com esse cansaco, voce percebeu menos vontade de fazer as coisas?",
            ),
            main.LiaTranscriptMessage(
                role="user",
                content="Mais na vontade de fazer as coisas. Parece que eu travo antes de comecar.",
            ),
            main.LiaTranscriptMessage(
                role="assistant",
                content="Entendi. E nisso tudo, como tem ficado seu sono e sua energia?",
            ),
            main.LiaTranscriptMessage(
                role="user",
                content="Meu sono ta baguncado e a energia bem baixa. Acordo ja meio sem animo.",
            ),
            main.LiaTranscriptMessage(
                role="assistant",
                content="Entendi. Isso tem aparecido na maior parte dos dias ou varia bastante?",
            ),
        ]
        main.update_topic_state(session, "opening_state", "estou meio cansado")
        main.update_topic_state(session, "main_focus", "cansaco e pouca vontade")
        main.update_topic_state(session, "distress_nature", "desanimo")
        main.update_topic_state(session, "functional_impact", "sono, energia e vontade")

        main.infer_topic_states(session, "varia bastante")

        self.assertTrue(session.topic_states["frequency_duration"].filled)
        self.assertEqual(session.topic_states["frequency_duration"].value, "varia bastante")
        self.assertNotEqual(main.next_lia_topic(session), "frequency_duration")

    def test_quick_pass_message_does_not_trigger_distress_question(self) -> None:
        session = self.build_session(stage="support", turn_count=2)
        analysis = main.fallback_lia_analysis(session, "so quis passar aqui rapidinho")

        lowered = main.normalize_for_match(analysis.assistant_reply or "")
        self.assertIn("podemos deixar por aqui", lowered)
        self.assertNotIn("desgasta", lowered)
        self.assertNotIn("o que mais pesou", lowered)

    def test_no_issue_message_can_close_lightly(self) -> None:
        session = self.build_session(stage="support", turn_count=2)
        analysis = main.fallback_lia_analysis(session, "nao tem nada pegando, so quis passar aqui")

        lowered = main.normalize_for_match(analysis.assistant_reply or "")
        self.assertIn("podemos deixar por aqui", lowered)
        self.assertNotIn("desgasta", lowered)

    def test_stop_signal_gets_simple_closing(self) -> None:
        session = self.build_session(stage="mood", turn_count=5)
        session.current_topic = "closing"
        main.update_topic_state(session, "main_focus", "trabalho")
        main.update_topic_state(session, "distress_nature", "desanimo")
        main.update_topic_state(session, "functional_impact", "sono e energia")
        main.update_topic_state(session, "frequency_duration", "na maior parte dos dias")
        analysis = main.fallback_lia_analysis(session, "acho que ja estou bem por agora")

        lowered = main.normalize_for_match(analysis.assistant_reply or "")
        self.assertTrue("fechar por aqui" in lowered or "parar por aqui" in lowered)

    def test_short_topic_answer_can_fill_current_topic(self) -> None:
        session = self.build_session(stage="anxiety", turn_count=3)
        session.current_topic = "distress_nature"

        main.infer_topic_states(session, "pressao")

        self.assertTrue(session.topic_states["distress_nature"].filled)
        self.assertEqual(session.topic_states["distress_nature"].value, "pressao")

    def test_simple_closing_reply_sounds_final(self) -> None:
        session = self.build_session(stage="mood", turn_count=5)
        main.update_topic_state(session, "main_focus", "cansaco")
        main.update_topic_state(session, "functional_impact", "sono e energia")
        main.update_topic_state(session, "frequency_duration", "na maior parte dos dias")

        reply = main.build_simple_closing_reply(session, "na maior parte dos dias")
        lowered = main.normalize_for_match(reply)

        self.assertIn("podemos fechar por aqui", lowered)
        self.assertNotIn("pode falar mais", lowered)

    def test_mood_support_phrase_can_vary_after_recent_use(self) -> None:
        session = self.build_session(stage="mood", turn_count=4)
        session.transcript = [
            main.LiaTranscriptMessage(
                role="assistant",
                content="Quando o cansaco acumula, ate falar disso ja pode parecer muito.",
            )
        ]

        support = main.build_contextual_support(session, "meu sono ta ruim e minha energia baixa", "mood")

        self.assertIsNotNone(support)
        self.assertNotEqual(support, "Quando o cansaco acumula, ate falar disso ja pode parecer muito.")


if __name__ == "__main__":
    unittest.main()
