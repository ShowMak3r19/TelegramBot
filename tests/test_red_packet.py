from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_bot.config import AppConfig, RedPacketConfig, RedPacketTemplateConfig
from telegram_bot.modules.base import ModuleCard
from telegram_bot.modules.red_packet import RedPacketModule, _classify_callback_result


SUCCESS_CALLBACK_MESSAGE = "你抢到了 13634 银元"
ELIGIBILITY_CALLBACK_MESSAGE = "红包前 10 秒仅限最近 20 位发言人领取。"
ENDED_CALLBACK_MESSAGE = "这个红包已经结束。"
UNKNOWN_CALLBACK_MESSAGE = "操作太频繁，请稍后再试。"


class FakeBotCallbackAnswer:
    def __init__(
        self,
        message: str | None = SUCCESS_CALLBACK_MESSAGE,
        *,
        alert: bool = False,
        url: str | None = None,
    ) -> None:
        self.message = message
        self.alert = alert
        self.url = url


class FakeMessage:
    def __init__(
        self,
        text: str,
        *,
        out: bool = False,
        buttons: list[list[object]] | None = None,
        chat_id: int | str = -1001,
        message_id: int = 10,
        click_results: list[object] | None = None,
    ) -> None:
        self.raw_text = text
        self.out = out
        self.buttons = buttons or []
        self.chat_id = chat_id
        self.id = message_id
        self.responses: list[str] = []
        self.clicked_buttons: list[str] = []
        self.click_results = list(click_results or [])

    async def respond(self, text: str) -> None:
        self.responses.append(text)

    async def click(self, *, text: str) -> object:
        result = self.click_results.pop(0) if self.click_results else FakeBotCallbackAnswer()
        if isinstance(result, BaseException):
            raise result
        self.clicked_buttons.append(text)
        return result


class FakeButton:
    def __init__(self, text: str) -> None:
        self.text = text


class RecordingMessage(FakeMessage):
    def __init__(
        self,
        text: str,
        *,
        events: list[tuple[str, object]],
        buttons: list[list[object]],
        chat_id: int | str = -1001,
        message_id: int = 10,
        fail_responses: int = 0,
        fail_clicks: int = 0,
        click_results: list[object] | None = None,
        response_started: asyncio.Event | None = None,
        response_release: asyncio.Event | None = None,
    ) -> None:
        super().__init__(
            text,
            buttons=buttons,
            chat_id=chat_id,
            message_id=message_id,
            click_results=click_results,
        )
        self.events = events
        self.fail_responses = fail_responses
        self.fail_clicks = fail_clicks
        self.response_started = response_started
        self.response_release = response_release

    async def respond(self, text: str) -> None:
        self.events.append(("respond", text))
        if self.fail_responses:
            self.fail_responses -= 1
            raise RuntimeError("pre-click message failed")
        await super().respond(text)
        if self.response_started is not None:
            self.response_started.set()
        if self.response_release is not None:
            await self.response_release.wait()

    async def click(self, *, text: str) -> object:
        self.events.append(("click", text))
        if self.fail_clicks:
            self.fail_clicks -= 1
            raise RuntimeError("initial click failed")
        return await super().click(text=text)


def make_button_module(
    *,
    auto_speech: bool = True,
    delay_after_speech: bool = False,
    send_delay_ms: int = 0,
    pre_click_messages: list[str] | None = None,
    choice_func: Callable[[list[str]], str] | None = None,
) -> RedPacketModule:
    return RedPacketModule(
        ModuleCard("red_packet", "Auto claim", "", "automation", enabled=True),
        RedPacketConfig(
            send_delay_ms=send_delay_ms,
            pre_click_messages=list(pre_click_messages if pre_click_messages is not None else ["hello"]),
            templates=[
                RedPacketTemplateConfig(
                    id="button-red-packet",
                    trigger_keywords=["button packet"],
                    button_texts=["Claim"],
                    send_message_before_click=auto_speech,
                    delay_before_click=delay_after_speech,
                )
            ],
        ),
        choice_func=choice_func,
    )


def callback_answer(message: str, *, alert: bool) -> FakeBotCallbackAnswer:
    return FakeBotCallbackAnswer(message, alert=alert)


def claim_key(message_id: int = 10) -> str:
    return f"message:-1001:{message_id}"


def test_callback_classifier_recognizes_real_success_message() -> None:
    result = callback_answer(SUCCESS_CALLBACK_MESSAGE, alert=False)

    assert _classify_callback_result(result) == "success"


def test_callback_classifier_recognizes_real_eligibility_message() -> None:
    result = callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True)

    assert _classify_callback_result(result) == "eligibility"


def test_callback_classifier_accepts_variable_eligibility_numbers() -> None:
    result = callback_answer("红包前 8 秒仅限最近 37 位发言人领取。", alert=True)

    assert _classify_callback_result(result) == "eligibility"


def test_callback_classifier_recognizes_real_ended_message() -> None:
    result = callback_answer(ENDED_CALLBACK_MESSAGE, alert=True)

    assert _classify_callback_result(result) == "ended"


def test_callback_classifier_prefers_terminal_over_embedded_eligibility_text() -> None:
    result = callback_answer(
        f"{ENDED_CALLBACK_MESSAGE} {ELIGIBILITY_CALLBACK_MESSAGE}",
        alert=True,
    )

    assert _classify_callback_result(result) == "ended"


def test_callback_classifier_treats_empty_message_as_unknown() -> None:
    result = FakeBotCallbackAnswer(message="", alert=False)

    assert _classify_callback_result(result) == "unknown"


def test_callback_classifier_treats_url_only_answer_as_unknown() -> None:
    result = FakeBotCallbackAnswer(message=None, alert=False, url="https://example.invalid/claim")

    assert _classify_callback_result(result) == "unknown"


def test_callback_classifier_treats_message_with_url_as_unknown() -> None:
    result = FakeBotCallbackAnswer(
        message=SUCCESS_CALLBACK_MESSAGE,
        alert=False,
        url="https://example.invalid/claim",
    )

    assert _classify_callback_result(result) == "unknown"


def test_callback_classifier_treats_unrecognized_message_as_unknown() -> None:
    result = callback_answer(UNKNOWN_CALLBACK_MESSAGE, alert=True)

    assert _classify_callback_result(result) == "unknown"


def test_red_packet_pre_click_config_roundtrip() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        config = AppConfig()
        config.red_packet = RedPacketConfig(
            send_delay_ms=1250,
            pre_click_messages=["hello, world", "second line"],
            templates=[
                RedPacketTemplateConfig(
                    id="button-red-packet",
                    trigger_keywords=["button packet"],
                    button_texts=["Claim"],
                    send_message_before_click=True,
                    delay_before_click=True,
                )
            ],
        )

        config.save(path)
        loaded = AppConfig.load(path)

    template = loaded.red_packet.templates[0]
    assert loaded.red_packet.send_delay_ms == 1250
    assert loaded.red_packet.pre_click_messages == ["hello, world", "second line"]
    assert template.send_message_before_click is True
    assert template.delay_before_click is True


def test_red_packet_old_config_defaults_to_no_speech_with_delay() -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(
            json.dumps(
                {
                    "red_packet": {
                        "send_delay_ms": 900,
                        "templates": [
                            {
                                "id": "legacy-button",
                                "trigger_keywords": ["button packet"],
                                "button_texts": ["Claim"],
                            },
                            {
                                "id": "legacy-second",
                                "trigger_keywords": ["second packet"],
                                "button_texts": ["Open"],
                            },
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )

        loaded = AppConfig.load(path)

    assert [template.id for template in loaded.red_packet.templates] == ["legacy-button", "legacy-second"]
    assert len(loaded.red_packet.templates) == 2
    assert loaded.red_packet.pre_click_messages == []
    assert all(template.send_message_before_click is False for template in loaded.red_packet.templates)
    assert all(template.delay_before_click is True for template in loaded.red_packet.templates)


def test_red_packet_without_auto_speech_treats_eligibility_as_terminal() -> None:
    events: list[tuple[str, object]] = []

    async def fake_sleep(seconds: float) -> None:
        events.append(("sleep", seconds))

    def unexpected_choice(messages: list[str]) -> str:
        raise AssertionError(f"choice should not be called: {messages}")

    original_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep
    try:
        module = make_button_module(
            auto_speech=False,
            delay_after_speech=True,
            send_delay_ms=2500,
            choice_func=unexpected_choice,
        )
        message = RecordingMessage(
            "button packet available",
            events=events,
            buttons=[[FakeButton("Claim")]],
            click_results=[callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True)],
        )
        duplicate = RecordingMessage(
            "button packet available",
            events=events,
            buttons=[[FakeButton("Claim")]],
        )

        result = asyncio.run(module.handle_message(message))
        duplicate_result = asyncio.run(module.handle_message(duplicate))
    finally:
        asyncio.sleep = original_sleep

    assert result.status == "handled"
    assert result.message == "red packet eligibility restriction"
    assert result.metadata["outcome"] == "eligibility"
    assert result.metadata["initial_outcome"] == "eligibility"
    assert result.metadata["retry_outcome"] == ""
    assert events == [("click", "Claim")]
    assert message.responses == []
    assert claim_key() in module.claimed_ids["button-red-packet"]
    assert duplicate_result.status == "ignored"
    assert duplicate.clicked_buttons == []


def test_red_packet_speaks_selected_message_then_delays_then_clicks() -> None:
    events: list[tuple[str, object]] = []
    choice_inputs: list[list[str]] = []

    async def fake_sleep(seconds: float) -> None:
        events.append(("sleep", seconds))

    def choose_second(messages: list[str]) -> str:
        choice_inputs.append(list(messages))
        return messages[1]

    original_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep
    try:
        module = make_button_module(
            auto_speech=True,
            delay_after_speech=True,
            send_delay_ms=1250,
            pre_click_messages=["hello, world", "second line"],
            choice_func=choose_second,
        )
        message = RecordingMessage(
            "button packet available",
            events=events,
            buttons=[[FakeButton("Claim")]],
            click_results=[
                callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True),
                callback_answer(SUCCESS_CALLBACK_MESSAGE, alert=False),
            ],
        )

        result = asyncio.run(module.handle_message(message))
    finally:
        asyncio.sleep = original_sleep

    assert result.status == "handled"
    assert result.message == "red packet claimed"
    assert result.metadata["outcome"] == "success"
    assert result.metadata["initial_outcome"] == "eligibility"
    assert result.metadata["retry_outcome"] == "success"
    assert result.metadata["initial_callback"] == (
        f"message={ELIGIBILITY_CALLBACK_MESSAGE} alert=True"
    )
    assert result.metadata["callback"] == f"message={SUCCESS_CALLBACK_MESSAGE} alert=False"
    assert result.metadata["initial_callback_message"] == ELIGIBILITY_CALLBACK_MESSAGE
    assert result.metadata["initial_callback_alert"] is True
    assert result.metadata["initial_callback_url"] == ""
    assert result.metadata["retry_callback_message"] == SUCCESS_CALLBACK_MESSAGE
    assert result.metadata["retry_callback_alert"] is False
    assert result.metadata["retry_callback_url"] == ""
    assert choice_inputs == [["hello, world", "second line"]]
    assert events == [
        ("click", "Claim"),
        ("respond", "second line"),
        ("sleep", 1.25),
        ("click", "Claim"),
    ]
    assert message.responses == ["second line"]
    assert message.clicked_buttons == ["Claim", "Claim"]
    assert claim_key() in module.claimed_ids["button-red-packet"]


def test_red_packet_logs_initial_callback_before_speaking() -> None:
    events: list[tuple[str, object]] = []

    class EventLogHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            events.append(("log", record.getMessage()))

    module = make_button_module(auto_speech=True)
    message = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
        click_results=[
            callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True),
            callback_answer(SUCCESS_CALLBACK_MESSAGE, alert=False),
        ],
    )
    callback_logger = logging.getLogger("telegram_bot.modules.red_packet")
    previous_level = callback_logger.level
    handler = EventLogHandler()
    callback_logger.addHandler(handler)
    callback_logger.setLevel(logging.INFO)
    try:
        result = asyncio.run(module.handle_message(message))
    finally:
        callback_logger.removeHandler(handler)
        callback_logger.setLevel(previous_level)

    initial_log_index = next(
        index
        for index, event in enumerate(events)
        if event[0] == "log" and "phase=initial outcome=eligibility" in str(event[1])
    )
    respond_index = events.index(("respond", "hello"))
    assert result.message == "red packet claimed"
    assert initial_log_index < respond_index


def test_red_packet_initial_success_stops_without_speech_and_marks_terminal() -> None:
    events: list[tuple[str, object]] = []
    module = make_button_module(auto_speech=True)
    message = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
        click_results=[callback_answer(SUCCESS_CALLBACK_MESSAGE, alert=False)],
    )
    duplicate = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
    )

    result = asyncio.run(module.handle_message(message))
    duplicate_result = asyncio.run(module.handle_message(duplicate))

    assert result.status == "handled"
    assert result.message == "red packet claimed"
    assert result.metadata["outcome"] == "success"
    assert result.metadata["initial_outcome"] == "success"
    assert result.metadata["retry_outcome"] == ""
    assert result.metadata["initial_callback"] == f"message={SUCCESS_CALLBACK_MESSAGE} alert=False"
    assert result.metadata["callback"] == f"message={SUCCESS_CALLBACK_MESSAGE} alert=False"
    assert events == [("click", "Claim")]
    assert message.responses == []
    assert message.clicked_buttons == ["Claim"]
    assert claim_key() in module.claimed_ids["button-red-packet"]
    assert duplicate_result.status == "ignored"
    assert duplicate.clicked_buttons == []


def test_red_packet_initial_ended_stops_without_speech_and_marks_terminal() -> None:
    events: list[tuple[str, object]] = []
    module = make_button_module(auto_speech=True)
    message = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
        click_results=[callback_answer(ENDED_CALLBACK_MESSAGE, alert=True)],
    )
    duplicate = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
    )

    result = asyncio.run(module.handle_message(message))
    duplicate_result = asyncio.run(module.handle_message(duplicate))

    assert result.status == "handled"
    assert result.message == "red packet ended"
    assert result.metadata["outcome"] == "ended"
    assert result.metadata["initial_outcome"] == "ended"
    assert events == [("click", "Claim")]
    assert message.responses == []
    assert claim_key() in module.claimed_ids["button-red-packet"]
    assert duplicate_result.status == "ignored"
    assert duplicate.clicked_buttons == []


def test_red_packet_initial_unknown_stops_without_speech_and_marks_terminal() -> None:
    events: list[tuple[str, object]] = []
    module = make_button_module(auto_speech=True)
    message = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
        click_results=[callback_answer(UNKNOWN_CALLBACK_MESSAGE, alert=True)],
    )
    duplicate = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
    )

    result = asyncio.run(module.handle_message(message))
    duplicate_result = asyncio.run(module.handle_message(duplicate))

    assert result.status == "handled"
    assert result.message == "red packet callback unrecognized"
    assert result.metadata["outcome"] == "unknown"
    assert result.metadata["initial_outcome"] == "unknown"
    assert events == [("click", "Claim")]
    assert message.responses == []
    assert claim_key() in module.claimed_ids["button-red-packet"]
    assert duplicate_result.status == "ignored"
    assert duplicate.clicked_buttons == []


def test_red_packet_auto_speech_without_delay_clicks_responds_and_clicks() -> None:
    events: list[tuple[str, object]] = []

    async def fake_sleep(seconds: float) -> None:
        events.append(("sleep", seconds))

    def choose_first(messages: list[str]) -> str:
        return messages[0]

    original_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep
    try:
        module = make_button_module(
            auto_speech=True,
            delay_after_speech=False,
            send_delay_ms=800,
            choice_func=choose_first,
        )
        message = RecordingMessage(
            "button packet available",
            events=events,
            buttons=[[FakeButton("Claim")]],
            click_results=[
                callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True),
                callback_answer(SUCCESS_CALLBACK_MESSAGE, alert=False),
            ],
        )

        result = asyncio.run(module.handle_message(message))
    finally:
        asyncio.sleep = original_sleep

    assert result.status == "handled"
    assert result.message == "red packet claimed"
    assert result.metadata["outcome"] == "success"
    assert events == [("click", "Claim"), ("respond", "hello"), ("click", "Claim")]
    assert message.responses == ["hello"]
    assert message.clicked_buttons == ["Claim", "Claim"]


def test_red_packet_retry_ended_reports_terminal_outcome_and_deduplicates() -> None:
    events: list[tuple[str, object]] = []
    module = make_button_module(auto_speech=True)
    message = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
        click_results=[
            callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True),
            callback_answer(ENDED_CALLBACK_MESSAGE, alert=True),
        ],
    )
    duplicate = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
    )

    result = asyncio.run(module.handle_message(message))
    duplicate_result = asyncio.run(module.handle_message(duplicate))

    assert result.status == "handled"
    assert result.message == "red packet ended"
    assert result.metadata["outcome"] == "ended"
    assert result.metadata["initial_outcome"] == "eligibility"
    assert result.metadata["retry_outcome"] == "ended"
    assert result.metadata["initial_callback"] == f"message={ELIGIBILITY_CALLBACK_MESSAGE} alert=True"
    assert result.metadata["callback"] == f"message={ENDED_CALLBACK_MESSAGE} alert=True"
    assert result.metadata["retry_callback_message"] == ENDED_CALLBACK_MESSAGE
    assert events == [("click", "Claim"), ("respond", "hello"), ("click", "Claim")]
    assert claim_key() in module.claimed_ids["button-red-packet"]
    assert duplicate_result.status == "ignored"
    assert duplicate.clicked_buttons == []


def test_red_packet_retry_eligibility_reports_restriction_and_deduplicates() -> None:
    events: list[tuple[str, object]] = []
    module = make_button_module(auto_speech=True)
    message = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
        click_results=[
            callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True),
            callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True),
        ],
    )
    duplicate = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
    )

    result = asyncio.run(module.handle_message(message))
    duplicate_result = asyncio.run(module.handle_message(duplicate))

    assert result.status == "handled"
    assert result.message == "red packet still ineligible after retry"
    assert result.metadata["outcome"] == "eligibility"
    assert result.metadata["initial_outcome"] == "eligibility"
    assert result.metadata["retry_outcome"] == "eligibility"
    assert result.metadata["callback"] == f"message={ELIGIBILITY_CALLBACK_MESSAGE} alert=True"
    assert result.metadata["retry_callback_message"] == ELIGIBILITY_CALLBACK_MESSAGE
    assert events == [("click", "Claim"), ("respond", "hello"), ("click", "Claim")]
    assert claim_key() in module.claimed_ids["button-red-packet"]
    assert duplicate_result.status == "ignored"
    assert duplicate.clicked_buttons == []


def test_red_packet_retry_unknown_reports_terminal_outcome_and_deduplicates() -> None:
    events: list[tuple[str, object]] = []
    module = make_button_module(auto_speech=True)
    message = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
        click_results=[
            callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True),
            callback_answer(UNKNOWN_CALLBACK_MESSAGE, alert=True),
        ],
    )
    duplicate = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
    )

    result = asyncio.run(module.handle_message(message))
    duplicate_result = asyncio.run(module.handle_message(duplicate))

    assert result.status == "handled"
    assert result.message == "red packet callback unrecognized"
    assert result.metadata["outcome"] == "unknown"
    assert result.metadata["initial_outcome"] == "eligibility"
    assert result.metadata["retry_outcome"] == "unknown"
    assert result.metadata["callback"] == f"message={UNKNOWN_CALLBACK_MESSAGE} alert=True"
    assert result.metadata["retry_callback_message"] == UNKNOWN_CALLBACK_MESSAGE
    assert events == [("click", "Claim"), ("respond", "hello"), ("click", "Claim")]
    assert claim_key() in module.claimed_ids["button-red-packet"]
    assert duplicate_result.status == "ignored"
    assert duplicate.clicked_buttons == []


def test_red_packet_initial_click_exception_fails_without_marking_and_can_retry() -> None:
    events: list[tuple[str, object]] = []
    module = make_button_module(auto_speech=True)
    message = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
        click_results=[RuntimeError("initial click failed")],
    )

    first_result = asyncio.run(module.handle_message(message))

    assert first_result.status == "failed"
    assert "initial click failed" in first_result.message
    assert first_result.metadata["outcome"] == ""
    assert first_result.metadata["initial_outcome"] == ""
    assert first_result.metadata["initial_click_error"] == "initial click failed"
    assert module.claimed_ids == {}
    assert message.responses == []

    second_result = asyncio.run(module.handle_message(message))

    assert second_result.status == "handled"
    assert second_result.message == "red packet claimed"
    assert events == [("click", "Claim"), ("click", "Claim")]
    assert claim_key() in module.claimed_ids["button-red-packet"]


def test_red_packet_retry_click_exception_fails_without_marking_and_can_retry() -> None:
    events: list[tuple[str, object]] = []
    module = make_button_module(auto_speech=True)
    message = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
        click_results=[
            callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True),
            RuntimeError("retry click failed"),
        ],
    )

    first_result = asyncio.run(module.handle_message(message))

    assert first_result.status == "failed"
    assert "retry click failed" in first_result.message
    assert first_result.metadata["outcome"] == "eligibility"
    assert first_result.metadata["initial_outcome"] == "eligibility"
    assert first_result.metadata["initial_callback_message"] == ELIGIBILITY_CALLBACK_MESSAGE
    assert first_result.metadata["retry_outcome"] == ""
    assert first_result.metadata["retry_click_error"] == "retry click failed"
    assert module.claimed_ids == {}
    assert message.responses == ["hello"]

    second_result = asyncio.run(module.handle_message(message))

    assert second_result.status == "handled"
    assert second_result.message == "red packet claimed"
    assert events == [
        ("click", "Claim"),
        ("respond", "hello"),
        ("click", "Claim"),
        ("click", "Claim"),
    ]
    assert claim_key() in module.claimed_ids["button-red-packet"]


def test_red_packet_pre_click_message_empty_fails_closed() -> None:
    events: list[tuple[str, object]] = []
    module = make_button_module(
        auto_speech=True,
        delay_after_speech=True,
        send_delay_ms=500,
        pre_click_messages=["", "   "],
    )
    message = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
        click_results=[callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True)],
    )

    result = asyncio.run(module.handle_message(message))

    assert result.status == "failed"
    assert result.message == "red packet pre-click messages are empty"
    assert events == [("click", "Claim")]
    assert message.responses == []
    assert message.clicked_buttons == ["Claim"]
    assert module.claimed_ids == {}


def test_red_packet_pre_click_message_failure_can_retry() -> None:
    events: list[tuple[str, object]] = []
    module = make_button_module(auto_speech=True)
    message = RecordingMessage(
        "button packet available",
        events=events,
        buttons=[[FakeButton("Claim")]],
        fail_responses=1,
        click_results=[
            callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True),
            callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True),
            callback_answer(SUCCESS_CALLBACK_MESSAGE, alert=False),
        ],
    )

    first_result = asyncio.run(module.handle_message(message))

    assert first_result.status == "failed"
    assert first_result.message == "red packet pre-click message failed: pre-click message failed"
    assert message.clicked_buttons == ["Claim"]
    assert module.claimed_ids == {}

    second_result = asyncio.run(module.handle_message(message))

    assert second_result.status == "handled"
    assert second_result.message == "red packet claimed"
    assert second_result.metadata["outcome"] == "success"
    assert events == [
        ("click", "Claim"),
        ("respond", "hello"),
        ("click", "Claim"),
        ("respond", "hello"),
        ("click", "Claim"),
    ]
    assert message.responses == ["hello"]
    assert message.clicked_buttons == ["Claim", "Claim", "Claim"]


def test_red_packet_concurrent_duplicate_runs_one_double_click_flow() -> None:
    events: list[tuple[str, object]] = []

    async def scenario() -> tuple[list[object], list[RecordingMessage]]:
        response_started = asyncio.Event()
        response_release = asyncio.Event()
        module = make_button_module(auto_speech=True)
        messages = [
            RecordingMessage(
                "button packet available",
                events=events,
                buttons=[[FakeButton("Claim")]],
                chat_id=-1001,
                message_id=77,
                click_results=[
                    callback_answer(ELIGIBILITY_CALLBACK_MESSAGE, alert=True),
                    callback_answer(SUCCESS_CALLBACK_MESSAGE, alert=False),
                ],
                response_started=response_started,
                response_release=response_release,
            )
            for _ in range(2)
        ]

        async def release_after_overlap() -> None:
            await response_started.wait()
            await asyncio.sleep(0)
            response_release.set()

        gathered = await asyncio.gather(
            module.handle_message(messages[0]),
            module.handle_message(messages[1]),
            release_after_overlap(),
        )
        return list(gathered[:2]), messages

    results, messages = asyncio.run(scenario())

    statuses = [result.status for result in results]
    assert statuses.count("handled") == 1
    assert statuses.count("ignored") == 1
    assert sum(len(message.responses) for message in messages) == 1
    assert sum(len(message.clicked_buttons) for message in messages) == 2
    assert [event for event in events if event[0] == "respond"] == [("respond", "hello")]
    assert [event for event in events if event[0] == "click"] == [
        ("click", "Claim"),
        ("click", "Claim"),
    ]


def test_red_packet_template_matches_and_sends_passphrase() -> None:
    module = RedPacketModule(
        ModuleCard("red_packet", "自动抢红包", "", "automation", enabled=True),
        RedPacketConfig(
            templates=[
                RedPacketTemplateConfig(
                    id="one",
                    name="默认红包",
                    trigger_keywords=["红包"],
                    id_markers=["红包id："],
                    passphrase_markers=["领取密令:"],
                )
            ]
        ),
    )
    message = FakeMessage("新的红包来了，红包id：ubsa4b\n领取密令: 口令123")

    result = asyncio.run(module.handle_message(message))

    assert result.status == "handled"
    assert result.metadata["template_id"] == "one"
    assert message.responses == ["口令123"]


def test_red_packet_template_requires_id_marker_when_configured() -> None:
    module = RedPacketModule(
        ModuleCard("red_packet", "自动抢红包", "", "automation", enabled=True),
        RedPacketConfig(
            templates=[
                RedPacketTemplateConfig(
                    id="one",
                    trigger_keywords=["红包"],
                    id_markers=["红包id："],
                    passphrase_markers=["领取密令:"],
                )
            ]
        ),
    )

    result = asyncio.run(module.handle_message(FakeMessage("新的红包来了，但没有编号")))

    assert result.status == "ignored"


def test_red_packet_config_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = AppConfig()
    config.red_packet.templates = [
        RedPacketTemplateConfig(
            id="one",
            name="抽奖模板",
            trigger_keywords=["抽奖"],
                    id_markers=["lottery-"],
                    passphrase_markers=["口令:"],
                    button_texts=["抢红包"],
                )
            ]
    config.save(path)

    loaded = AppConfig.load(path)

    assert loaded.red_packet.templates[0].name == "抽奖模板"
    assert loaded.red_packet.templates[0].trigger_keywords == ["抽奖"]
    assert loaded.red_packet.templates[0].id_markers == ["lottery-"]
    assert loaded.red_packet.templates[0].passphrase_markers == ["口令:"]
    assert loaded.red_packet.templates[0].button_texts == ["抢红包"]


def test_red_packet_extracts_next_non_empty_line() -> None:
    module = RedPacketModule(
        ModuleCard("red_packet", "自动抢红包", "", "automation", enabled=True),
        RedPacketConfig(
            templates=[
                RedPacketTemplateConfig(
                    id="one",
                    trigger_keywords=["拼手气红包"],
                    id_markers=["红包ID:"],
                    passphrase_markers=["发送下方口令领取："],
                )
            ]
        ),
    )
    message = FakeMessage("发了一个拼手气红包\n红包ID: 82AT7A\n\n发送下方口令领取：\n能吗")

    result = asyncio.run(module.handle_message(message))

    assert result.status == "handled"
    assert message.responses == ["能吗"]


def test_red_packet_clicks_matching_button() -> None:
    module = RedPacketModule(
        ModuleCard("red_packet", "自动抢红包", "", "automation", enabled=True),
        RedPacketConfig(
            templates=[
                RedPacketTemplateConfig(
                    id="button-red-packet",
                    trigger_keywords=["拼手气红包"],
                    button_texts=["抢红包"],
                )
            ]
        ),
    )
    message = FakeMessage(
        "🎁 拼手气红包\n发红包人: yet 💎\n总银元: 50000\n份数: 5\n点击下方按钮参与\n30 分钟内有效",
        buttons=[[FakeButton("抢红包")]],
        chat_id=-1000000000004,
        message_id=995730,
    )

    result = asyncio.run(module.handle_message(message))

    assert result.status == "handled"
    assert result.message == "red packet claimed"
    assert result.metadata["outcome"] == "success"
    assert result.metadata["template_id"] == "button-red-packet"
    assert result.metadata["button_text"] == "抢红包"
    assert result.metadata["red_packet_id"] == "message:-1000000000004:995730"
    assert message.clicked_buttons == ["抢红包"]
    assert message.responses == []


def test_red_packet_button_click_skips_delay_when_switch_off() -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    original_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep
    try:
        module = RedPacketModule(
            ModuleCard("red_packet", "自动抢红包", "", "automation", enabled=True),
            RedPacketConfig(
                send_delay_ms=2500,
                templates=[
                        RedPacketTemplateConfig(
                            id="button-red-packet",
                            trigger_keywords=["拼手气红包"],
                            button_texts=["抢红包"],
                            delay_before_click=False,
                        )
                ],
            ),
        )
        message = FakeMessage("拼手气红包\n点击下方按钮参与", buttons=[[FakeButton("抢红包")]])

        result = asyncio.run(module.handle_message(message))
    finally:
        asyncio.sleep = original_sleep

    assert result.status == "handled"
    assert message.clicked_buttons == ["抢红包"]
    assert sleep_calls == []


def test_red_packet_skips_duplicate_button_message_within_ttl() -> None:
    now = [1000.0]
    module = RedPacketModule(
        ModuleCard("red_packet", "自动抢红包", "", "automation", enabled=True),
        RedPacketConfig(
            templates=[
                RedPacketTemplateConfig(
                    id="button-red-packet",
                    trigger_keywords=["拼手气红包"],
                    button_texts=["抢红包"],
                )
            ]
        ),
        now_func=lambda: now[0],
    )
    first = FakeMessage("拼手气红包\n点击下方按钮参与", buttons=[[FakeButton("抢红包")]], message_id=1)
    second = FakeMessage("拼手气红包\n点击下方按钮参与", buttons=[[FakeButton("抢红包")]], message_id=1)

    first_result = asyncio.run(module.handle_message(first))
    second_result = asyncio.run(module.handle_message(second))

    assert first_result.status == "handled"
    assert second_result.status == "ignored"
    assert first.clicked_buttons == ["抢红包"]
    assert second.clicked_buttons == []


def test_red_packet_button_enabled_template_still_sends_passphrase_without_button() -> None:
    module = RedPacketModule(
        ModuleCard("red_packet", "自动抢红包", "", "automation", enabled=True),
        RedPacketConfig(
            templates=[
                RedPacketTemplateConfig(
                    id="one",
                    trigger_keywords=["拼手气红包"],
                    id_markers=["红包ID:"],
                    passphrase_markers=["发送下方口令领取："],
                    button_texts=["抢红包"],
                )
            ]
        ),
    )
    message = FakeMessage("发了一个拼手气红包\n红包ID: 82AT7A\n发送下方口令领取：\n能吗")

    result = asyncio.run(module.handle_message(message))

    assert result.status == "handled"
    assert message.responses == ["能吗"]
    assert message.clicked_buttons == []


def test_red_packet_skips_duplicate_id_within_ttl() -> None:
    now = [1000.0]
    module = RedPacketModule(
        ModuleCard("red_packet", "自动抢红包", "", "automation", enabled=True),
        RedPacketConfig(
            templates=[
                RedPacketTemplateConfig(
                    id="one",
                    trigger_keywords=["红包"],
                    id_markers=["红包ID:"],
                    passphrase_markers=["口令:"],
                )
            ]
        ),
        now_func=lambda: now[0],
    )
    text = "红包来了\n红包ID: ABC123\n口令: open"
    first = FakeMessage(text)
    second = FakeMessage(text)

    first_result = asyncio.run(module.handle_message(first))
    second_result = asyncio.run(module.handle_message(second))

    assert first_result.status == "handled"
    assert second_result.status == "ignored"
    assert first.responses == ["open"]
    assert second.responses == []


def test_red_packet_allows_same_id_after_48_hours() -> None:
    now = [1000.0]
    module = RedPacketModule(
        ModuleCard("red_packet", "自动抢红包", "", "automation", enabled=True),
        RedPacketConfig(
            templates=[
                RedPacketTemplateConfig(
                    id="one",
                    trigger_keywords=["红包"],
                    id_markers=["红包ID:"],
                    passphrase_markers=["口令:"],
                )
            ]
        ),
        now_func=lambda: now[0],
    )
    text = "红包来了\n红包ID: ABC123\n口令: open"
    first = FakeMessage(text)
    second = FakeMessage(text)

    first_result = asyncio.run(module.handle_message(first))
    now[0] += 48 * 60 * 60 + 1
    second_result = asyncio.run(module.handle_message(second))

    assert first_result.status == "handled"
    assert second_result.status == "handled"
    assert second.responses == ["open"]


def test_red_packet_extracts_quoted_lottery_keyword_only() -> None:
    module = RedPacketModule(
        ModuleCard("red_packet", "自动抢红包", "", "automation", enabled=True),
        RedPacketConfig(
            templates=[
                RedPacketTemplateConfig(
                    id="lottery",
                    trigger_keywords=["新的抽奖已经创建", "抽奖信息"],
                    id_markers=["抽奖 ID："],
                    passphrase_markers=["参与关键词："],
                )
            ]
        ),
    )
    message = FakeMessage(
        "新的抽奖已经创建\n"
        "抽奖信息\n"
        "  抽奖 ID：96f661e9-19ac-41c2-ba2e-103e9cb4b7cb\n"
        "参与设置\n"
        "  参与关键词：「点姐 点姐 让我看看头像吧」\n\n"
        "建议先私聊机器人，这样中奖、参加时可以便可以收到机器人的私聊通知"
    )

    result = asyncio.run(module.handle_message(message))

    assert result.status == "handled"
    assert result.metadata["red_packet_id"] == "96f661e9-19ac-41c2-ba2e-103e9cb4b7cb"
    assert message.responses == ["点姐 点姐 让我看看头像吧"]


def test_red_packet_ignores_slash_command_passphrase() -> None:
    module = RedPacketModule(
        ModuleCard("red_packet", "自动抢红包", "", "automation", enabled=True),
        RedPacketConfig(
            templates=[
                RedPacketTemplateConfig(
                    id="lottery",
                    trigger_keywords=["抽奖"],
                    id_markers=["抽奖 ID："],
                    passphrase_markers=["参与关键词："],
                )
            ]
        ),
    )
    message = FakeMessage("新的抽奖\n抽奖 ID：abc\n参与关键词：「/start danger」")

    result = asyncio.run(module.handle_message(message))

    assert result.status == "ignored"
    assert message.responses == []


def test_red_packet_ignores_outgoing_messages() -> None:
    module = RedPacketModule(
        ModuleCard("red_packet", "自动抢红包", "", "automation", enabled=True),
        RedPacketConfig(
            templates=[
                RedPacketTemplateConfig(
                    id="one",
                    trigger_keywords=["拼手气红包"],
                    id_markers=["红包ID:"],
                    passphrase_markers=["发送下方口令领取："],
                )
            ]
        ),
    )
    message = FakeMessage("发了一个拼手气红包\n红包ID: 82AT7A\n发送下方口令领取：\n能吗", out=True)

    result = asyncio.run(module.handle_message(message))

    assert result.status == "ignored"
    assert message.responses == []
