from __future__ import annotations

import asyncio
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram_bot.config import SendRedPacketConfig, SendRedPacketTemplateConfig
from telegram_bot.modules.base import ModuleCard
import telegram_bot.modules.send_red_packet as send_red_packet_module
from telegram_bot.modules.send_red_packet import (
    MIN_PACKET_AMOUNT,
    STRICT_MIN_PACKET_AMOUNT,
    SendRedPacketModule,
    _generate_sequence_quiz,
    _generate_square_pattern_quiz,
    minimum_packet_amount_for_chat,
    parse_cancel_packet_command,
    parse_create_command,
    parse_math_quiz_command,
    split_amounts,
    validate_math_quiz_request,
    validate_packet_request,
)


RED_PACKET = "\u7ea2\u5305"
RED_PACKET_LIST = "\u7ea2\u5305\u5217\u8868"
CANCEL_RED_PACKET = "\u64a4\u9500\u7ea2\u5305"
PASS = "\u54c8\u54c8\u54c8"
TEST_PASS = "\u53e3\u4ee4"
TEST_TEMPLATE = "\u6d4b\u8bd5\u7ea2\u5305"
LUCKY_TEMPLATE = "\u62fc\u624b\u6c14\u7ea2\u5305"
AUDIENCE_CHAT_ID = -1000000000001


class FakeSent:
    def __init__(self, message_id: int) -> None:
        self.id = message_id
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []

    async def send_message(self, chat_id: int | str, text: str, **kwargs: object) -> FakeSent:
        message_id = len(self.sent) + 100
        sent = FakeSent(message_id)
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs, "id": message_id, "message": sent})
        return sent

    async def edit_message(self, chat_id: int | str, message_id: int, text: str, **kwargs: object) -> None:
        self.edits.append({"chat_id": chat_id, "message_id": message_id, "text": text, "kwargs": kwargs})


class FakeMessage:
    def __init__(
        self,
        text: str,
        *,
        out: bool,
        sender_id: str,
        sender_name: str,
        message_id: int,
        chat_id: int = -1001,
    ) -> None:
        self.raw_text = text
        self.out = out
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.chat_id = chat_id
        self.id = message_id
        self.deleted = False

    async def delete(self) -> None:
        self.deleted = True


class FakeEvent:
    def __init__(self, message: FakeMessage, client: FakeClient) -> None:
        self.message = message
        self.client = client
        self.chat_id = message.chat_id


def make_module(
    tmp_path: Path,
    seed: int = 1,
    config: SendRedPacketConfig | None = None,
    transfer_message_delete_seconds: float | None = None,
) -> SendRedPacketModule:
    return SendRedPacketModule(
        ModuleCard("send_red_packet", "send", "", "automation", enabled=True),
        config or SendRedPacketConfig(state_store="send_state.json", strict_min_packet_group_ids=[str(AUDIENCE_CHAT_ID)]),
        tmp_path,
        rng=random.Random(seed),
        transfer_message_delete_seconds=transfer_message_delete_seconds,
    )


def test_send_red_packet_parse_command() -> None:
    parsed = parse_create_command(f"{RED_PACKET} 10000 10 {PASS}", [RED_PACKET])
    slash_parsed = parse_create_command(f"/{RED_PACKET} 10000 10 /start", [RED_PACKET, f"/{RED_PACKET}"])
    math_parsed = parse_math_quiz_command("/math 6666", ["/math"])
    cancel_parsed = parse_cancel_packet_command(f"{CANCEL_RED_PACKET} abcd2e")

    assert parsed == {"total_amount": 10000, "packet_count": 10, "passphrase": PASS}
    assert slash_parsed == {"total_amount": 10000, "packet_count": 10, "passphrase": "/start"}
    assert math_parsed == {"reward_amount": 6666}
    assert cancel_parsed == "ABCD2E"


def test_split_amounts_are_precomputed_and_sum_to_total() -> None:
    amounts = split_amounts(10000, 10, random.Random(1))
    small_amounts = split_amounts(199, 2, random.Random(1))

    assert len(amounts) == 10
    assert sum(amounts) == 10000
    assert all(amount >= MIN_PACKET_AMOUNT for amount in amounts)
    assert len(small_amounts) == 2
    assert sum(small_amounts) == 199
    assert all(amount >= MIN_PACKET_AMOUNT for amount in small_amounts)
    assert split_amounts(3, 2, random.Random(1)) == []
    assert split_amounts(200, 2, random.Random(1), min_packet_amount=STRICT_MIN_PACKET_AMOUNT) == []
    assert split_amounts(202, 2, random.Random(1), min_packet_amount=STRICT_MIN_PACKET_AMOUNT) == [
        STRICT_MIN_PACKET_AMOUNT,
        STRICT_MIN_PACKET_AMOUNT,
    ]


def test_send_red_packet_rejects_normal_total_below_minimum_per_packet(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=17)
    create = FakeEvent(FakeMessage(f"{RED_PACKET} 3 2 {PASS}", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)

    result = asyncio.run(module.handle_message(create))

    assert result.status == "handled"
    assert create.message.deleted is True
    assert not module.active_packets
    assert f"\u81f3\u5c11 {MIN_PACKET_AMOUNT}" in str(client.sent[0]["text"])
    assert validate_packet_request(3, 2, PASS, 100)


def test_send_red_packet_allows_small_packets_outside_strict_group(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=18)
    create = FakeEvent(FakeMessage(f"{RED_PACKET} 20 10 {PASS}", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)

    result = asyncio.run(module.handle_message(create))
    packet = next(iter(module.active_packets.values()))

    assert result.status == "handled"
    assert result.metadata["min_packet_amount"] == MIN_PACKET_AMOUNT
    assert packet.chat_id == "-1001"
    assert sum(packet.allocations) == 20
    assert all(amount >= MIN_PACKET_AMOUNT for amount in packet.allocations)


def test_send_red_packet_rejects_audience_total_below_strict_minimum(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=19)
    create = FakeEvent(
        FakeMessage(
            f"{RED_PACKET} 200 2 {PASS}",
            out=True,
            sender_id="self",
            sender_name="ExampleUser",
            message_id=1,
            chat_id=AUDIENCE_CHAT_ID,
        ),
        client,
    )

    result = asyncio.run(module.handle_message(create))

    assert result.status == "handled"
    assert create.message.deleted is True
    assert not module.active_packets
    assert f"\u81f3\u5c11 {STRICT_MIN_PACKET_AMOUNT}" in str(client.sent[0]["text"])
    assert validate_packet_request(200, 2, PASS, 100, STRICT_MIN_PACKET_AMOUNT)


def test_send_red_packet_uses_audience_strict_minimum(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=20)
    create = FakeEvent(
        FakeMessage(
            f"{RED_PACKET} 202 2 {PASS}",
            out=True,
            sender_id="self",
            sender_name="ExampleUser",
            message_id=1,
            chat_id=AUDIENCE_CHAT_ID,
        ),
        client,
    )

    result = asyncio.run(module.handle_message(create))
    packet = next(iter(module.active_packets.values()))

    assert result.status == "handled"
    assert result.metadata["min_packet_amount"] == STRICT_MIN_PACKET_AMOUNT
    assert minimum_packet_amount_for_chat(module.config, str(AUDIENCE_CHAT_ID)) == STRICT_MIN_PACKET_AMOUNT
    assert packet.chat_id == str(AUDIENCE_CHAT_ID)
    assert packet.allocations == [STRICT_MIN_PACKET_AMOUNT, STRICT_MIN_PACKET_AMOUNT]


def test_math_quiz_number_patterns_use_plain_text_numbers() -> None:
    quizzes = [
        _generate_sequence_quiz(random.Random(1)),
        _generate_square_pattern_quiz(random.Random(1)),
    ]

    for quiz in quizzes:
        assert "\ufe0f\u20e3" not in quiz.question
        assert "\U0001f539" not in quiz.question
        assert "\u627e\u89c4\u5f8b" in quiz.question
        assert "?" in quiz.question


def test_math_quiz_rejects_normal_reward_below_minimum(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=21)
    create = FakeEvent(FakeMessage("/math 1", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)

    result = asyncio.run(module.handle_message(create))

    assert result.status == "handled"
    assert not module.active_packets
    assert f"\u4e0d\u80fd\u5c0f\u4e8e {MIN_PACKET_AMOUNT}" in str(client.sent[0]["text"])
    assert validate_math_quiz_request(1, MIN_PACKET_AMOUNT)


def test_math_quiz_rejects_audience_reward_below_strict_minimum(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=22)
    create = FakeEvent(
        FakeMessage(
            "/math 100",
            out=True,
            sender_id="self",
            sender_name="ExampleUser",
            message_id=1,
            chat_id=AUDIENCE_CHAT_ID,
        ),
        client,
    )

    result = asyncio.run(module.handle_message(create))

    assert result.status == "handled"
    assert not module.active_packets
    assert f"\u4e0d\u80fd\u5c0f\u4e8e {STRICT_MIN_PACKET_AMOUNT}" in str(client.sent[0]["text"])
    assert validate_math_quiz_request(100, STRICT_MIN_PACKET_AMOUNT)


def test_send_red_packet_create_claim_and_summary(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=2)
    create = FakeEvent(FakeMessage(f"{RED_PACKET} 300 2 {PASS}", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)

    create_result = asyncio.run(module.handle_message(create))
    packet = next(iter(module.active_packets.values()))
    allocations = list(packet.allocations)
    first = FakeEvent(FakeMessage(PASS, out=False, sender_id="u1", sender_name="A", message_id=2), client)
    second = FakeEvent(FakeMessage(PASS, out=False, sender_id="u2", sender_name="B", message_id=3), client)
    first_result = asyncio.run(module.handle_message(first))
    second_result = asyncio.run(module.handle_message(second))

    assert create_result.status == "handled"
    assert "ExampleUser" in str(client.sent[0]["text"])
    assert f"<code>{PASS}</code>" in str(client.sent[0]["text"])
    assert client.sent[0]["kwargs"] == {"parse_mode": "html"}
    assert create.message.deleted is True
    assert first_result.metadata["amount"] == allocations[0]
    assert second_result.metadata["amount"] == allocations[1]
    assert str(client.sent[1]["text"]) == f"+{allocations[0]}"
    assert client.sent[1]["kwargs"] == {"reply_to": 2}
    assert str(client.sent[2]["text"]) == f"+{allocations[1]}"
    assert not client.edits
    assert "\u9886\u53d6\u8be6\u60c5" in str(client.sent[3]["text"])
    assert "<blockquote expandable>" in str(client.sent[3]["text"])
    assert "\u624b\u6c14\u6700\u4f73" in str(client.sent[3]["text"])
    assert client.sent[3]["kwargs"] == {"reply_to": 100, "parse_mode": "html"}
    assert not module.active_packets


def test_send_red_packet_transfer_message_auto_deletes(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=13, transfer_message_delete_seconds=0.01)

    async def run_flow() -> None:
        create = FakeEvent(FakeMessage(f"{RED_PACKET} 100 1 {PASS}", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)
        await module.handle_message(create)
        claim = FakeEvent(FakeMessage(PASS, out=False, sender_id="u1", sender_name="A", message_id=2), client)
        await module.handle_message(claim)
        await asyncio.sleep(0.05)

    asyncio.run(run_flow())

    transfer = client.sent[1]["message"]
    summary = client.sent[2]["message"]
    assert str(client.sent[1]["text"]).startswith("+")
    assert getattr(transfer, "deleted") is True
    assert getattr(summary, "deleted") is False


def test_send_red_packet_uses_matching_template_prefix(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(
        tmp_path,
        seed=4,
        config=SendRedPacketConfig(
            templates=[
                SendRedPacketTemplateConfig(id="one", name=LUCKY_TEMPLATE, command_prefixes=[RED_PACKET]),
                SendRedPacketTemplateConfig(id="two", name=TEST_TEMPLATE, command_prefixes=[TEST_TEMPLATE]),
            ],
            state_store="send_state.json",
        ),
    )
    create = FakeEvent(FakeMessage(f"{TEST_TEMPLATE} 300 2 {TEST_PASS}", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)

    result = asyncio.run(module.handle_message(create))
    packet = next(iter(module.active_packets.values()))

    assert result.metadata["template_id"] == "two"
    assert packet.template_id == "two"
    assert TEST_TEMPLATE in str(client.sent[0]["text"])
    assert f"<code>{TEST_PASS}</code>" in str(client.sent[0]["text"])
    assert create.message.deleted is True


def test_send_red_packet_allows_slash_passphrase(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=5)
    create = FakeEvent(FakeMessage(f"/{RED_PACKET} 100 1 /start", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)

    result = asyncio.run(module.handle_message(create))

    assert result.status == "handled"
    assert "<code>/start</code>" in str(client.sent[0]["text"])
    assert create.message.deleted is True


def test_send_red_packet_lists_unfinished_packets(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=6)
    create = FakeEvent(FakeMessage(f"{RED_PACKET} 300 2 {PASS}", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)
    asyncio.run(module.handle_message(create))
    packet = next(iter(module.active_packets.values()))
    claim = FakeEvent(FakeMessage(PASS, out=False, sender_id="u1", sender_name="A", message_id=2), client)
    asyncio.run(module.handle_message(claim))
    list_command = FakeEvent(FakeMessage(RED_PACKET_LIST, out=True, sender_id="self", sender_name="ExampleUser", message_id=3), client)

    result = asyncio.run(module.handle_message(list_command))
    sent = client.sent[-1]
    text = str(sent["text"])

    assert result.status == "handled"
    assert result.metadata["active_count"] == 1
    assert list_command.message.deleted is True
    assert sent["kwargs"] == {"parse_mode": "html"}
    assert "<b>\u672a\u9886\u5b8c\u7ea2\u5305\u5217\u8868</b>" in text
    assert f"<code>{packet.id}</code>" in text
    assert "\u8fdb\u5ea6: 1/2" in text
    assert f"<code>{PASS}</code>" in text


def test_send_red_packet_lists_empty_state(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=7)
    list_command = FakeEvent(FakeMessage(RED_PACKET_LIST, out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)

    result = asyncio.run(module.handle_message(list_command))

    assert result.status == "handled"
    assert result.metadata["active_count"] == 0
    assert list_command.message.deleted is True
    assert client.sent[-1]["text"] == "\u5f53\u524d\u6ca1\u6709\u672a\u9886\u5b8c\u7684\u7ea2\u5305\u3002"
    assert client.sent[-1]["kwargs"] == {"parse_mode": "html"}


def test_send_red_packet_list_is_scoped_to_current_chat(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=8)
    first_chat_create = FakeEvent(
        FakeMessage(f"{RED_PACKET} 300 2 first-chat", out=True, sender_id="self", sender_name="ExampleUser", message_id=1, chat_id=-1001),
        client,
    )
    second_chat_create = FakeEvent(
        FakeMessage(f"{RED_PACKET} 300 2 second-chat", out=True, sender_id="self", sender_name="ExampleUser", message_id=2, chat_id=-2002),
        client,
    )
    asyncio.run(module.handle_message(first_chat_create))
    asyncio.run(module.handle_message(second_chat_create))
    first_packet = [packet for packet in module.active_packets.values() if packet.chat_id == "-1001"][0]
    second_packet = [packet for packet in module.active_packets.values() if packet.chat_id == "-2002"][0]
    list_command = FakeEvent(
        FakeMessage(RED_PACKET_LIST, out=True, sender_id="self", sender_name="ExampleUser", message_id=3, chat_id=-1001),
        client,
    )

    result = asyncio.run(module.handle_message(list_command))
    text = str(client.sent[-1]["text"])

    assert result.status == "handled"
    assert result.metadata["active_count"] == 1
    assert f"<code>{first_packet.id}</code>" in text
    assert f"<code>{second_packet.id}</code>" not in text


def test_send_red_packet_cancel_removes_packet_and_edits_announcement(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=14)
    create = FakeEvent(FakeMessage(f"{RED_PACKET} 300 2 {PASS}", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)
    asyncio.run(module.handle_message(create))
    packet = next(iter(module.active_packets.values()))
    cancel = FakeEvent(FakeMessage(f"{CANCEL_RED_PACKET} {packet.id.lower()}", out=True, sender_id="self", sender_name="ExampleUser", message_id=2), client)

    result = asyncio.run(module.handle_message(cancel))
    claim = FakeEvent(FakeMessage(PASS, out=False, sender_id="u1", sender_name="A", message_id=3), client)
    claim_result = asyncio.run(module.handle_message(claim))

    assert result.status == "handled"
    assert result.metadata["cancelled"] is True
    assert cancel.message.deleted is True
    assert packet.id not in module.active_packets
    assert len(client.edits) == 1
    assert client.edits[0]["message_id"] == 100
    assert client.edits[0]["kwargs"] == {"parse_mode": "html"}
    assert "\u5df2\u64a4\u9500" in str(client.edits[0]["text"])
    assert claim_result.status == "ignored"
    assert len(client.sent) == 1


def test_send_red_packet_cancel_is_scoped_to_current_chat(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=15)
    create = FakeEvent(FakeMessage(f"{RED_PACKET} 300 2 {PASS}", out=True, sender_id="self", sender_name="ExampleUser", message_id=1, chat_id=-1001), client)
    asyncio.run(module.handle_message(create))
    packet = next(iter(module.active_packets.values()))
    cancel = FakeEvent(FakeMessage(f"{CANCEL_RED_PACKET} {packet.id}", out=True, sender_id="self", sender_name="ExampleUser", message_id=2, chat_id=-2002), client)

    result = asyncio.run(module.handle_message(cancel))

    assert result.status == "handled"
    assert result.metadata["cancelled"] is False
    assert packet.id in module.active_packets
    assert cancel.message.deleted is True
    assert "\u672a\u627e\u5230" in str(client.sent[-1]["text"])
    assert not client.edits


def test_math_quiz_cancel_removes_packet_and_edits_question(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=16)
    create = FakeEvent(FakeMessage("/math 6666", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)
    asyncio.run(module.handle_message(create))
    packet = next(iter(module.active_packets.values()))
    cancel = FakeEvent(FakeMessage(f"{CANCEL_RED_PACKET} {packet.id}", out=True, sender_id="self", sender_name="ExampleUser", message_id=2), client)

    result = asyncio.run(module.handle_message(cancel))

    assert result.status == "handled"
    assert result.metadata["template_type"] == "math_quiz"
    assert result.metadata["cancelled"] is True
    assert packet.id not in module.active_packets
    assert cancel.message.deleted is True
    assert len(client.edits) == 1
    assert client.edits[0]["message_id"] == 100
    assert "\u5df2\u64a4\u9500" in str(client.edits[0]["text"])
    assert "\u9898\u76ee" in str(client.edits[0]["text"])


def test_send_red_packet_ignores_creator_claim(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=3)
    create = FakeEvent(FakeMessage(f"{RED_PACKET} 100 1 {PASS}", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)
    asyncio.run(module.handle_message(create))
    creator_claim = FakeEvent(FakeMessage(PASS, out=False, sender_id="self", sender_name="ExampleUser", message_id=2), client)

    result = asyncio.run(module.handle_message(creator_claim))

    assert result.status == "ignored"
    assert len(client.sent) == 1


def test_send_red_packet_concurrent_final_claim_sends_one_summary(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=9)
    create = FakeEvent(FakeMessage(f"{RED_PACKET} 100 1 {PASS}", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)
    asyncio.run(module.handle_message(create))

    original_sender_display_name = send_red_packet_module.sender_display_name

    async def slow_sender_display_name(event):
        await asyncio.sleep(0.05)
        return getattr(event.message, "sender_name", "User")

    async def run_claims():
        first = FakeEvent(FakeMessage(PASS, out=False, sender_id="u1", sender_name="A", message_id=2), client)
        second = FakeEvent(FakeMessage(PASS, out=False, sender_id="u1", sender_name="A", message_id=3), client)
        return await asyncio.gather(module.handle_message(first), module.handle_message(second))

    try:
        send_red_packet_module.sender_display_name = slow_sender_display_name
        results = asyncio.run(run_claims())
    finally:
        send_red_packet_module.sender_display_name = original_sender_display_name

    assert sorted(result.status for result in results) == ["handled", "ignored"]
    assert sum(1 for item in client.sent if str(item["text"]).startswith("+")) == 1
    assert sum(1 for item in client.sent if "<blockquote expandable>" in str(item["text"])) == 1


def test_math_quiz_create_claim_and_edit_completed_question(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=10)
    create = FakeEvent(FakeMessage("/math 6666", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)

    create_result = asyncio.run(module.handle_message(create))
    packet = next(iter(module.active_packets.values()))
    answer = packet.passphrase
    wrong = FakeEvent(FakeMessage("999999", out=False, sender_id="u1", sender_name="A", message_id=2), client)
    right = FakeEvent(FakeMessage(answer, out=False, sender_id="u2", sender_name="B", message_id=3), client)
    wrong_result = asyncio.run(module.handle_message(wrong))
    right_result = asyncio.run(module.handle_message(right))

    assert create_result.status == "handled"
    assert create_result.metadata["reward_amount"] == 6666
    assert create.message.deleted is True
    assert "\u76f4\u63a5\u56de\u590d\u6570\u5b57\u4f5c\u7b54" in str(client.sent[0]["text"])
    assert "\u7b54\u6848 8" not in str(client.sent[0]["text"])
    assert wrong_result.status == "ignored"
    assert right_result.status == "handled"
    assert client.sent[1]["text"] == "+6666"
    assert client.sent[1]["kwargs"] == {"reply_to": 3}
    assert len(client.edits) == 1
    assert client.edits[0]["message_id"] == 100
    assert client.edits[0]["kwargs"] == {"parse_mode": "html"}
    assert "\u5df2\u5b8c\u6210\u89e3\u7b54" in str(client.edits[0]["text"])
    assert f"<code>{answer}</code>" in str(client.edits[0]["text"])
    assert not module.active_packets


def test_math_quiz_keeps_legacy_answer_prefix_compatible(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=12)
    create = FakeEvent(FakeMessage("/math 6666", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)
    asyncio.run(module.handle_message(create))
    packet = next(iter(module.active_packets.values()))
    right = FakeEvent(FakeMessage(f"\u7b54\u6848 {packet.passphrase}", out=False, sender_id="u1", sender_name="A", message_id=2), client)

    result = asyncio.run(module.handle_message(right))

    assert result.status == "handled"
    assert client.sent[1]["text"] == "+6666"


def test_math_quiz_concurrent_correct_answers_settle_once(tmp_path: Path) -> None:
    client = FakeClient()
    module = make_module(tmp_path, seed=11)
    create = FakeEvent(FakeMessage("/math 6666", out=True, sender_id="self", sender_name="ExampleUser", message_id=1), client)
    asyncio.run(module.handle_message(create))
    packet = next(iter(module.active_packets.values()))

    async def run_answers():
        first = FakeEvent(FakeMessage(packet.passphrase, out=False, sender_id="u1", sender_name="A", message_id=2), client)
        second = FakeEvent(FakeMessage(packet.passphrase, out=False, sender_id="u2", sender_name="B", message_id=3), client)
        return await asyncio.gather(module.handle_message(first), module.handle_message(second))

    results = asyncio.run(run_answers())

    assert sorted(result.status for result in results) == ["handled", "ignored"]
    assert sum(1 for item in client.sent if str(item["text"]) == "+6666") == 1
    assert len(client.edits) == 1


if __name__ == "__main__":
    import tempfile

    test_send_red_packet_parse_command()
    test_split_amounts_are_precomputed_and_sum_to_total()
    test_math_quiz_number_patterns_use_plain_text_numbers()
    with tempfile.TemporaryDirectory() as tmp:
        test_math_quiz_rejects_normal_reward_below_minimum(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_math_quiz_rejects_audience_reward_below_strict_minimum(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_rejects_normal_total_below_minimum_per_packet(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_allows_small_packets_outside_strict_group(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_rejects_audience_total_below_strict_minimum(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_uses_audience_strict_minimum(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_create_claim_and_summary(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_transfer_message_auto_deletes(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_uses_matching_template_prefix(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_allows_slash_passphrase(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_lists_unfinished_packets(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_lists_empty_state(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_list_is_scoped_to_current_chat(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_cancel_removes_packet_and_edits_announcement(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_cancel_is_scoped_to_current_chat(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_math_quiz_cancel_removes_packet_and_edits_question(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_ignores_creator_claim(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_send_red_packet_concurrent_final_claim_sends_one_summary(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_math_quiz_create_claim_and_edit_completed_question(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_math_quiz_keeps_legacy_answer_prefix_compatible(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_math_quiz_concurrent_correct_answers_settle_once(Path(tmp))
    print("PASS test_send_red_packet")
