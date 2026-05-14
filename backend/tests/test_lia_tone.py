import unittest
from unittest.mock import patch
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

        self.assertIn("Oi, Davi. Eu sou a Lia.", contents)
        self.assertIn(
            "Eu estou aqui para te ouvir com calma, ajudar a organizar o que voce esta sentindo e, se fizer sentido, te orientar daqui para a frente.",
            contents,
        )
        self.assertIn("Nao precisa ter as palavras certas agora. Pode comecar do seu jeito.", contents)
        self.assertNotIn("Me conta, como voce ta hoje?", contents)
        self.assertNotIn("Esse pode ser nosso primeiro cuidado por aqui. Nao precisa acertar as palavras.", contents)

    def test_lia_knowledge_base_is_loaded_into_system_prompt(self) -> None:
        knowledge = main.normalize_for_match(main.load_lia_knowledge_base())
        prompt = main.normalize_for_match(main.build_lia_system_prompt("support"))

        self.assertIn("assistente virtual de apoio", knowledge)
        self.assertIn("fora de escopo", knowledge)
        self.assertIn("receita", knowledge)
        self.assertIn("codigo", knowledge)
        self.assertIn("triagem", knowledge)
        self.assertIn("base interna da lia", prompt)
        self.assertIn("nao cite esta base para o usuario", prompt)
        self.assertIn("pedidos fora do escopo nao devem apagar o contexto emocional anterior", prompt)

    def test_returning_contact_does_not_dump_previous_summary(self) -> None:
        user = main.User(nome="Davi", email="davi@example.com", hashed_password="x")
        memory = LiaMemorySnapshot(
            is_first_contact=False,
            summary="Temas que ja apareceram no seu cuidado: ansiedade, sono e trabalho.",
            recent_summary="a pressao do trabalho voltou a pesar bastante",
            recent_conversations=[
                main.LiaRecentInteraction(
                    created_at=datetime.now(timezone.utc),
                    summary="partimos de musica e falamos bastante sobre trabalho, sono e ansiedade",
                    topics=["trabalho", "sono", "ansiedade"],
                )
            ],
        )

        messages = main.build_lia_welcome_messages(user, memory)
        joined = main.normalize_for_match(" ".join(item.content for item in messages))

        self.assertEqual(len(messages), 3)
        self.assertIn("bom te ver por aqui", joined)
        self.assertIn("retomar algo", joined)
        self.assertNotIn("da ultima vez ficou comigo", joined)
        self.assertNotIn("ansiedade sono e trabalho", joined)
        self.assertNotIn("partimos de musica", joined)

    def test_recent_interaction_includes_transcript_for_psychologist_view(self) -> None:
        interaction = LiaInteraction(
            id="lia-1",
            usuario_id="user-1",
            summary="Conversa registrada.",
            report="Relatorio breve.",
            transcript=[
                {"role": "assistant", "content": "Oi, eu sou a Lia."},
                {"role": "user", "content": "Estou sobrecarregado."},
            ],
            topics=["trabalho"],
            created_at=datetime.now(timezone.utc),
        )

        recent = main.build_lia_recent_interaction(interaction)

        self.assertEqual([item.role for item in recent.transcript], ["assistant", "user"])
        self.assertEqual(recent.transcript[1].content, "Estou sobrecarregado.")

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

        self.assertIn("trabalho", summary)
        self.assertNotIn("partimos de", main.normalize_for_match(summary))
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

    def test_question_uses_concrete_financial_and_caregiving_context(self) -> None:
        session = self.build_session(stage="anxiety", turn_count=1)
        session.current_topic = "distress_context"

        user_message = (
            "estou com minha mente cheia e preocupada, tenho muitas contas para pagar "
            "e um filho para cuidar, nao sei como lidar com tudo isso sozinha"
        )
        question = main.build_contextual_question(session, user_message, "anxiety") or ""
        reply = main.fallback_lia_analysis(session, user_message).assistant_reply or ""

        normalized_question = main.normalize_for_match(question)
        normalized_reply = main.normalize_for_match(reply)
        self.assertIn("contas", normalized_question)
        self.assertIn("filho", normalized_question)
        self.assertIn("sozinha", normalized_question)
        self.assertNotIn("trabalho, da rotina ou de alguma situacao especifica", normalized_question)
        self.assertIn("contas", normalized_reply)
        self.assertIn("filho", normalized_reply)

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

    def test_one_month_duration_closes_without_time_distortion_reply(self) -> None:
        session = self.build_session(stage="mood", turn_count=6)
        session.current_topic = "frequency_duration"
        main.update_topic_state(session, "main_focus", "mente cheia e muitas tarefas")
        main.update_topic_state(session, "distress_nature", "tristeza, desanimo")
        main.update_topic_state(session, "distress_context", "situacao especifica")
        main.update_topic_state(session, "functional_impact", "humor, vontade")
        session.transcript = [
            main.LiaTranscriptMessage(role="user", content="Oi LIA, eu estou me sentindo com a cabeça cheia, muitas tarefas para eu fazer"),
            main.LiaTranscriptMessage(role="user", content="eu não sei responder, mas me vem uma tristeza e um desanimo, uma vontade de chorar"),
            main.LiaTranscriptMessage(role="user", content="talvez alguma situação especifica, não sei"),
            main.LiaTranscriptMessage(role="user", content="isso já vem faz um tempo"),
            main.LiaTranscriptMessage(role="user", content="sinto que vai fazer um mês, ou talvez mais"),
        ]

        main.infer_topic_states(session, "sinto que vai fazer um mês, ou talvez mais")
        analysis = main.fallback_lia_analysis(session, "sinto que vai fazer um mês, ou talvez mais")
        enough = True
        should_close = main.should_close_lia_session(session, analysis, "mood", enough)
        normalized = main.normalize_for_match(analysis.assistant_reply or "")

        self.assertTrue(session.topic_states["frequency_duration"].filled)
        self.assertTrue(should_close)
        self.assertFalse(main.reply_respects_support_context(session, "sinto que vai fazer um mês, ou talvez mais", "Entendi que voce esta sentindo um tempo diferente, como se o tempo estivesse passando mais rapido."))
        self.assertNotIn("tempo estivesse passando", normalized)

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

        self.assertIn("podemos parar por aqui", lowered)
        self.assertIn("colocado essa parte para fora", lowered)
        self.assertNotIn("pode falar mais", lowered)
        self.assertNotIn("guardar o essencial", lowered)

    def test_followup_closing_reply_can_be_more_final(self) -> None:
        session = self.build_session(stage="closing", turn_count=6)
        session.followup_mode = True
        session.followup_turns_left = 0

        reply = main.build_simple_closing_reply(session, "tem mais uma coisa")
        lowered = main.normalize_for_match(reply)

        self.assertIn("triagem", lowered)
        self.assertIn("baixar um pouco o ritmo", lowered)
        self.assertIn("para por aqui", lowered)
        self.assertNotIn("organizar uma parte importante", lowered)

    def test_followup_mode_keeps_conversation_open_for_extra_turn(self) -> None:
        session = self.build_session(stage="closing", turn_count=6)
        session.current_topic = "closing"
        session.followup_mode = True
        session.followup_turns_left = 2
        session.transcript = [
            main.LiaTranscriptMessage(role="assistant", content="Podemos fechar por aqui."),
            main.LiaTranscriptMessage(role="assistant", content="Pode continuar. Eu sigo com voce daqui."),
        ]

        analysis = main.LiaAnalysis(
            assistant_reply="Entendi. O que mais tem pesado nisso desde que voce voltou a falar?",
            reflection="Entendi.",
            next_question="O que mais tem pesado nisso desde que voce voltou a falar?",
            risk_level="none",
            mood_value=2,
            gad7_scores=[2, None, None, None, None, None, None],
            phq9_scores=[None, 2, None, 2, None, None, None, None, None],
            ready_to_close=True,
            recommended_stage="support",
        )

        data = main.LiaTurnInput(session=session, message="O que mais tem me pegado e a irritacao.")
        user = main.User(nome="Davi", email="davi@example.com", hashed_password="x")

        with patch.object(main, "should_offer_pause", return_value=False), patch.object(
            main, "analyze_lia_turn", return_value=(analysis, False)
        ), patch.object(main, "should_close_lia_session", return_value=True), patch.object(
            main, "save_lia_session_draft", return_value=True
        ) as draft_mock, patch.object(main, "save_lia_session_results", return_value=True) as result_mock:
            response = main.lia_message(data, current_user=user, db=None)

        self.assertFalse(response.session.completed)
        self.assertTrue(response.session.followup_mode)
        self.assertFalse(response.session.followup_finished)
        self.assertEqual(response.session.followup_turns_left, 1)
        self.assertNotIn("Quer encerrar por aqui?", response.session.transcript[-1].content)
        self.assertNotIn("fechar por aqui", main.normalize_for_match(response.session.transcript[-1].content))
        draft_mock.assert_called_once()
        result_mock.assert_not_called()

    def test_followup_answers_professional_help_question_before_script(self) -> None:
        session = self.build_session(stage="closing", turn_count=6)
        session.followup_mode = True
        session.followup_turns_left = 2
        session.transcript = [
            main.LiaTranscriptMessage(role="user", content="minha cabeca nao desliga quando chego em casa"),
            main.LiaTranscriptMessage(role="assistant", content="Pode continuar. Eu sigo com voce daqui."),
        ]

        reply = main.build_followup_continuation_reply(
            session,
            "Lia, eu nao sei o que eu posso fazer, sera que conversar com esse doutor Davi pode me ajudar?",
        )
        lowered = main.normalize_for_match(reply)

        self.assertIn("pode ajudar", lowered)
        self.assertIn("profissional", lowered)
        self.assertIn("nao precisa chegar la com tudo pronto", lowered)
        self.assertNotIn("quando isso aparece em casa", lowered)

    def test_followup_does_not_treat_noise_as_meaningful_context(self) -> None:
        session = self.build_session(stage="closing", turn_count=6)
        session.followup_mode = True
        session.followup_turns_left = 2
        session.transcript = [
            main.LiaTranscriptMessage(role="assistant", content="Pode continuar. Eu sigo com voce daqui."),
        ]

        reply = main.normalize_for_match(main.build_followup_continuation_reply(session, "ain"))

        self.assertIn("nao consegui pegar bem", reply)
        self.assertNotIn("quando isso aparece em casa", reply)

    def test_returning_contact_answers_professional_help_question(self) -> None:
        session = self.build_session(stage="support", turn_count=1)
        session.memory.is_first_contact = False
        session.current_topic = "main_focus"
        user_message = "quero saber antes da minha consulta se o doutor Davi pode me ajudar?"

        reply = main.normalize_for_match(main.build_scope_guard_reply(session, user_message) or "")

        self.assertIn("pode ajudar", reply)
        self.assertIn("profissional", reply)
        self.assertIn("consulta", reply)
        self.assertNotIn("o que mais ficou na sua cabeca hoje", reply)

    def test_scope_guard_redirects_unrelated_question_progressively(self) -> None:
        session = self.build_session(stage="support", turn_count=1)

        first = main.normalize_for_match(main.build_scope_guard_reply(session, "qual e a capital da Franca?") or "")
        second = main.normalize_for_match(main.build_scope_guard_reply(session, "faz um codigo em python pra mim") or "")
        third = main.normalize_for_match(main.build_scope_guard_reply(session, "calcule uma conta de matematica") or "")

        self.assertIn("foge um pouco do meu papel", first)
        self.assertIn("apoio, bem-estar e triagem", second)
        self.assertIn("vou manter esse limite", third)
        self.assertEqual(session.off_scope_count, 3)

    def test_scope_guard_allows_user_distress_to_follow_script(self) -> None:
        session = self.build_session(stage="support", turn_count=1)

        reply = main.build_scope_guard_reply(session, "nao tenho dormido bem e estou sobrecarregado")

        self.assertIsNone(reply)
        self.assertEqual(session.off_scope_count, 0)

    def test_figurative_distress_is_treated_as_distress_not_creative_image(self) -> None:
        session = self.build_session(stage="support", turn_count=1)
        user_message = "estou sentindo que minha cabeca vai explodir, estou com muitos problemas para resolver"

        analysis = main.fallback_lia_analysis(session, user_message)
        reply = main.normalize_for_match(analysis.assistant_reply)

        self.assertIn("cabeca", reply)
        self.assertIn("limite", reply)
        self.assertIn("qual problema parece mais urgente", reply)
        self.assertNotIn("nao precisa transformar isso em problema", reply)
        self.assertNotIn("partir dessa imagem", reply)

    def test_work_offense_followup_stays_anchored_to_user_context(self) -> None:
        session = self.build_session(stage="support", turn_count=2)
        session.current_topic = "main_focus"
        session.transcript = [
            main.LiaTranscriptMessage(
                role="user",
                content="minha cabeca vai explodir, tenho muitos problemas para resolver",
            )
        ]

        question = main.normalize_for_match(main.build_contextual_question(session, "as ofensas que recebo no trabalho", "support") or "")

        self.assertIn("ofensas", question)
        self.assertIn("trabalho", question)
        self.assertIn("?", question)
        self.assertNotIn("vida profissional", question)

    def test_recipe_request_is_blocked_even_after_support_context(self) -> None:
        session = self.build_session(stage="support", turn_count=3)
        session.transcript = [
            main.LiaTranscriptMessage(role="user", content="as ofensas que recebo no trabalho"),
        ]

        reply = main.normalize_for_match(
            main.build_scope_guard_reply(session, "quero uma receita de macarronada a bolonhesa") or ""
        )

        self.assertIn("nao consigo seguir por receita", reply)
        self.assertIn("ofensas", reply)
        self.assertIn("trabalho", reply)
        self.assertNotIn("ingredientes", reply)
        self.assertNotIn("modo de preparo", reply)

    def test_model_recipe_reply_is_rejected_by_support_validator(self) -> None:
        session = self.build_session(stage="support", turn_count=3)
        session.transcript = [
            main.LiaTranscriptMessage(role="user", content="as ofensas que recebo no trabalho"),
        ]
        model_reply = "Vou te dar uma receita: ingredientes, macarrao, carne moida, cebola picada e modo de preparo."

        self.assertFalse(
            main.reply_respects_support_context(
                session,
                "quero uma receita de macarronada a bolonhesa",
                model_reply,
            )
        )

    def test_followup_final_close_marks_finished(self) -> None:
        session = self.build_session(stage="closing", turn_count=7)
        session.current_topic = "closing"
        session.followup_mode = True
        session.followup_turns_left = 1
        session.transcript = [
            main.LiaTranscriptMessage(role="assistant", content="Pode continuar. Eu sigo com voce daqui."),
        ]

        analysis = main.LiaAnalysis(
            assistant_reply="Entendi.",
            reflection="Entendi.",
            next_question=None,
            risk_level="none",
            mood_value=2,
            gad7_scores=[2, None, None, None, None, None, None],
            phq9_scores=[None, 2, None, 2, None, None, None, None, None],
            ready_to_close=True,
            recommended_stage="support",
        )
        data = main.LiaTurnInput(session=session, message="Tambem estou me afastando das pessoas.")
        user = main.User(nome="Davi", email="davi@example.com", hashed_password="x")

        with patch.object(main, "should_offer_pause", return_value=False), patch.object(
            main, "analyze_lia_turn", return_value=(analysis, False)
        ), patch.object(main, "should_close_lia_session", return_value=True), patch.object(
            main, "save_lia_session_results", return_value=True
        ) as result_mock:
            response = main.lia_message(data, current_user=user, db=None)

        self.assertTrue(response.session.completed)
        self.assertTrue(response.session.followup_finished)
        self.assertIn("triagem", main.normalize_for_match(response.session.transcript[-1].content))
        result_mock.assert_called_once()

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

    def test_music_topic_does_not_sound_delicate_on_first_turn(self) -> None:
        session = self.build_session(stage="support", turn_count=1)
        analysis = main.fallback_lia_analysis(session, "podemos falar de musica?")

        lowered = main.normalize_for_match(analysis.assistant_reply or "")
        self.assertNotIn("isso soa delicado", lowered)
        self.assertIn("claro", lowered)
        self.assertIn("o que voce mais curte nisso", lowered)

    def test_analyze_lia_turn_prefers_llm_when_enabled(self) -> None:
        session = self.build_session(stage="support", turn_count=1)
        expected = main.LiaAnalysis(
            assistant_reply="Claro. Qual tipo de musica te pega mais facil?",
            reflection="Claro.",
            next_question="Qual tipo de musica te pega mais facil?",
            risk_level="none",
            mood_value=4,
            gad7_scores=[None] * 7,
            phq9_scores=[None] * 9,
            ready_to_close=False,
            recommended_stage="support",
        )

        with patch.object(main, "OLLAMA_ENABLED", True), patch.object(
            main,
            "analyze_lia_turn_with_llm",
            return_value=(expected, True),
        ) as llm_mock:
            analysis, using_ollama = main.analyze_lia_turn(session, "podemos falar de musica?")

        llm_mock.assert_called_once_with(session, "podemos falar de musica?")
        self.assertTrue(using_ollama)
        self.assertEqual(analysis.assistant_reply, expected.assistant_reply)

    def test_rejects_reply_that_misreads_clear_cansado_message(self) -> None:
        session = self.build_session(stage="support", turn_count=1)
        session.transcript = [main.LiaTranscriptMessage(role="assistant", content="Oi.")]
        analysis = main.LiaAnalysis(
            assistant_reply=(
                "Nao sei bem o que isso significa para voce. "
                "Voce se sente cansado? E agora, uma pergunta: o que mais te preocupa hoje?"
            ),
            reflection="teste",
            next_question="O que mais te preocupa hoje?",
            risk_level="none",
            mood_value=3,
            gad7_scores=[None] * 7,
            phq9_scores=[None] * 9,
            ready_to_close=False,
            recommended_stage="support",
        )

        with self.assertRaisesRegex(ValueError, "misread a clear user message"):
            main.refine_lia_analysis(session, analysis, "estou me sentindo cansado")

    def test_rejects_reply_with_doente_or_question_for_lia(self) -> None:
        session = self.build_session(stage="support", turn_count=2)
        session.transcript = [main.LiaTranscriptMessage(role="assistant", content="Oi.")]
        analysis = main.LiaAnalysis(
            assistant_reply=(
                "Entendo que seja normal ter dias assim. "
                "Voce se sente cansado de alguma coisa em particular ou esta apenas sendo um pouco mais doente? "
                "E voce tem uma pergunta para mim sobre isso?"
            ),
            reflection="teste",
            next_question="E voce tem uma pergunta para mim sobre isso?",
            risk_level="none",
            mood_value=3,
            gad7_scores=[None] * 7,
            phq9_scores=[None] * 9,
            ready_to_close=False,
            recommended_stage="support",
        )

        with self.assertRaisesRegex(ValueError, "misread a clear user message"):
            main.refine_lia_analysis(session, analysis, "estou um pouco cansado")

    def test_rejects_reply_with_self_reference_from_lia(self) -> None:
        session = self.build_session(stage="support", turn_count=2)
        session.transcript = [main.LiaTranscriptMessage(role="assistant", content="Oi.")]
        analysis = main.LiaAnalysis(
            assistant_reply=(
                "Sabe, eu tambem fui muito cansada ultimamente. "
                "Mas e bom saber que voce esta aqui."
            ),
            reflection="teste",
            next_question=None,
            risk_level="none",
            mood_value=3,
            gad7_scores=[None] * 7,
            phq9_scores=[None] * 9,
            ready_to_close=False,
            recommended_stage="support",
        )

        with self.assertRaisesRegex(ValueError, "misread a clear user message"):
            main.refine_lia_analysis(session, analysis, "as vezes, estou ficando bastante tempo na cama")

    def test_analyze_lia_turn_with_llm_falls_back_when_rewrite_is_bad(self) -> None:
        session = self.build_session(stage="support", turn_count=1)

        with patch.object(
            main,
            "rewrite_lia_from_analysis",
            return_value="Eu tambem ando cansada ultimamente. Voce tem uma pergunta para mim?",
        ):
            analysis, using_ollama = main.analyze_lia_turn_with_llm(session, "estou um pouco cansado")

        lowered = main.normalize_for_match(analysis.assistant_reply or "")
        self.assertFalse(using_ollama)
        self.assertIn("cansaco", lowered)
        self.assertNotIn("eu tambem", lowered)

    def test_build_lia_rewrite_seed_keeps_question_from_script(self) -> None:
        session = self.build_session(stage="mood", turn_count=1)
        analysis = main.LiaAnalysis(
            assistant_reply="Entendi. O cansaco parece estar pesando em voce. Junto com esse cansaco, voce percebeu menos vontade de fazer as coisas?",
            reflection="Entendi. O cansaco parece estar pesando em voce.",
            next_question="Junto com esse cansaco, voce percebeu menos vontade de fazer as coisas?",
            risk_level="none",
            mood_value=3,
            gad7_scores=[None] * 7,
            phq9_scores=[None] * 9,
            ready_to_close=False,
            recommended_stage="mood",
        )

        seed = main.build_lia_rewrite_seed(session, "estou cansado", analysis)
        lowered = main.normalize_for_match(seed)
        self.assertIn("pergunta permitida", lowered)
        self.assertIn("menos vontade de fazer as coisas", lowered)

    def test_rejects_model_leak_reply(self) -> None:
        session = self.build_session(stage="support", turn_count=2)
        session.transcript = [main.LiaTranscriptMessage(role="assistant", content="Oi.")]
        analysis = main.LiaAnalysis(
            assistant_reply=(
                "Ultima mensagem do usuario: estou cansado. "
                "Resposta anterior da Lia: Entendi. "
                "Reescreva agora a melhor resposta final."
            ),
            reflection="teste",
            next_question=None,
            risk_level="none",
            mood_value=3,
            gad7_scores=[None] * 7,
            phq9_scores=[None] * 9,
            ready_to_close=False,
            recommended_stage="support",
        )

        with self.assertRaisesRegex(ValueError, "misread a clear user message"):
            main.refine_lia_analysis(session, analysis, "estou cansado")


if __name__ == "__main__":
    unittest.main()
