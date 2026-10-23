from __future__ import annotations

import asyncio
import base64
import io
import json
import urllib.error
from pathlib import Path

import pytest

from telegram_bot.config import AIConfig, AIImageConfig, AIProviderConfig
from telegram_bot.modules.ai_image import (
    AIImageModule,
    build_xai_imagine_payload,
    extract_image_prompt,
    format_image_caption,
    format_image_status_message,
    resolve_image_api_size,
    save_image_api_result,
)
from telegram_bot.modules.base import ModuleCard


TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


class FakeMessage:
    def __init__(self, text: str, *, out: bool = True, is_reply: bool = False, reply: "FakeMessage | None" = None, message_id: int = 10) -> None:
        self.raw_text = text
        self.out = out
        self.is_reply = is_reply
        self._reply = reply
        self.edits: list[str] = []
        self.deleted = False
        self.chat_id = 123
        self.id = message_id
        self.media = False

    async def edit(self, text: str, **kwargs: object) -> None:
        self.edits.append(text)

    async def delete(self) -> None:
        self.deleted = True

    async def get_reply_message(self) -> "FakeMessage | None":
        return self._reply


class FakeClient:
    def __init__(self) -> None:
        self.sent_files: list[dict[str, object]] = []

    async def send_file(self, chat_id: int, **kwargs: object) -> None:
        self.sent_files.append({"chat_id": chat_id, **kwargs})


class FakeEvent:
    def __init__(self, message: FakeMessage) -> None:
        self.message = message
        self.chat_id = message.chat_id
        self.client = FakeClient()


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeBytesResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def __enter__(self) -> "FakeBytesResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.content


def test_extract_image_prompt_matches_legacy_draw_prefix() -> None:
    config = AIImageConfig()

    assert extract_image_prompt("/draw 一只猫", config) == "一只猫"
    assert extract_image_prompt("/draw", config) == ""
    assert extract_image_prompt("/ai 一只猫", config) is None


def test_resolve_image_api_size_supports_legacy_ratio_auto() -> None:
    assert resolve_image_api_size("1K", "auto") == "auto"
    assert resolve_image_api_size("1K", "16:9") == "1824x1024"
    assert resolve_image_api_size("123x456", "1:1") == "123x456"


def test_image_messages_wrap_prompt_in_expandable_quote() -> None:
    status = format_image_status_message("画一张海报", "正在生成图片……", "gpt-image-2", "16:9", "1K")
    caption = format_image_caption("引用内容生成图片", "gpt-image-2", "16:9", "1K")

    assert "<blockquote expandable>画一张海报</blockquote>" in status
    assert "<blockquote expandable>引用内容生成图片</blockquote>" in caption
    assert "<b>引用内容</b>" not in status


def test_reply_image_generation_sends_file_as_reply_to_original(tmp_path: Path) -> None:
    config = AIConfig(
        reply_provider=AIProviderConfig(base_url="http://example.test/v1", api_key="reply-key", model="gpt-5.5", enabled=True),
        image_provider=AIProviderConfig(base_url="", api_key="", model="gpt-image-2", enabled=True),
        image=AIImageConfig(output_dir=str(tmp_path / "images"), settings_store=str(tmp_path / "image_settings.json")),
    )
    module = AIImageModule(ModuleCard("ai_image", "AI Image", "", "ai", enabled=True), config, tmp_path)
    original = FakeMessage("原消息内容", out=False, message_id=77)
    trigger = FakeMessage("/draw 画成海报", is_reply=True, reply=original, message_id=88)
    event = FakeEvent(trigger)

    def fake_generate(prompt: str, output_path: Path, reference_image_path: Path | None = None) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(TINY_PNG)
        return output_path

    module._generate_image_with_openai_compatible_api = fake_generate  # type: ignore[method-assign]

    result = asyncio.run(module.handle_message(event))

    assert result.status == "handled"
    assert event.client.sent_files
    assert event.client.sent_files[0]["reply_to"] == 77
    assert trigger.deleted is True


def test_image_model_setting_command_updates_settings_file(tmp_path: Path) -> None:
    config = AIConfig(
        image_provider=AIProviderConfig(model="old", enabled=True),
        image=AIImageConfig(settings_store=str(tmp_path / "image_settings.json")),
    )
    module = AIImageModule(ModuleCard("ai_image", "AI Image", "", "ai", enabled=True), config)
    message = FakeMessage("/draw_model gpt-image-2")

    result = asyncio.run(module.handle_message(FakeEvent(message)))

    assert result.status == "handled"
    assert config.image_provider.model == "gpt-image-2"
    assert (tmp_path / "image_settings.json").exists()


@pytest.mark.parametrize("model", ["grok-imagine-image", "grok-imagine-image-quality"])
def test_xai_imagine_generation_uses_native_dimension_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    model: str,
) -> None:
    config = AIConfig(
        image_provider=AIProviderConfig(
            provider_type="xai-imagine",
            base_url="https://images.example.test/v1",
            api_key="test-key",
            model=model,
            enabled=True,
        ),
        image=AIImageConfig(size="1K", ratio="auto", quality="standard", output_dir=str(tmp_path)),
    )
    module = AIImageModule(ModuleCard("ai_image", "AI Image", "", "ai", enabled=True), config, tmp_path)
    captured: list[object] = []

    def fake_urlopen(request: object, timeout: float) -> FakeHTTPResponse:
        captured.append(request)
        return FakeHTTPResponse({"data": [{"b64_json": base64.b64encode(TINY_PNG).decode("ascii")}]})

    monkeypatch.setattr("telegram_bot.modules.ai_image.urllib.request.urlopen", fake_urlopen)

    output_path = module._generate_image_with_openai_compatible_api("draw a circle", tmp_path / f"{model}.png")

    assert output_path.read_bytes() == TINY_PNG
    request = captured[0]
    assert request.full_url == "https://images.example.test/v1/images/generations"
    assert request.get_header("Content-type") == "application/json"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload == {
        "model": model,
        "prompt": "draw a circle",
        "n": 1,
        "aspect_ratio": "auto",
        "resolution": "1k",
    }


def test_openai_generation_keeps_openai_image_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = AIConfig(
        image_provider=AIProviderConfig(
            provider_type="openai-compatible",
            base_url="https://images.example.test/v1",
            api_key="test-key",
            model="gpt-image-2",
            enabled=True,
        ),
        image=AIImageConfig(size="1K", ratio="16:9", quality="high", output_dir=str(tmp_path)),
    )
    module = AIImageModule(ModuleCard("ai_image", "AI Image", "", "ai", enabled=True), config, tmp_path)
    captured: list[object] = []

    def fake_urlopen(request: object, timeout: float) -> FakeHTTPResponse:
        captured.append(request)
        return FakeHTTPResponse({"data": [{"b64_json": base64.b64encode(TINY_PNG).decode("ascii")}]})

    monkeypatch.setattr("telegram_bot.modules.ai_image.urllib.request.urlopen", fake_urlopen)

    module._generate_image_with_openai_compatible_api("draw a circle", tmp_path / "openai.png")

    request = captured[0]
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data.decode("utf-8")) == {
        "model": "gpt-image-2",
        "prompt": "draw a circle",
        "size": "1824x1024",
        "n": 1,
        "quality": "high",
    }


def test_xai_imagine_edit_uses_json_data_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = AIConfig(
        image_provider=AIProviderConfig(
            provider_type="xai-imagine",
            base_url="https://images.example.test/v1",
            api_key="test-key",
            model="grok-imagine-image-quality",
            enabled=True,
        ),
        image=AIImageConfig(size="2K", ratio="16:9", quality="high", output_dir=str(tmp_path)),
    )
    module = AIImageModule(ModuleCard("ai_image", "AI Image", "", "ai", enabled=True), config, tmp_path)
    reference_path = tmp_path / "reference.png"
    reference_path.write_bytes(TINY_PNG)
    captured: list[object] = []

    def fake_urlopen(request: object, timeout: float) -> FakeHTTPResponse:
        captured.append(request)
        return FakeHTTPResponse({"data": [{"b64_json": base64.b64encode(TINY_PNG).decode("ascii")}]})

    monkeypatch.setattr("telegram_bot.modules.ai_image.urllib.request.urlopen", fake_urlopen)

    module._generate_image_with_openai_compatible_api("make it green", tmp_path / "edited.png", reference_path)

    request = captured[0]
    assert request.full_url == "https://images.example.test/v1/images/edits"
    assert request.get_header("Content-type") == "application/json"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["model"] == "grok-imagine-image-quality"
    assert payload["prompt"] == "make it green"
    assert payload["resolution"] == "2k"
    assert "aspect_ratio" not in payload
    assert "quality" not in payload
    assert "n" not in payload
    assert payload["image"]["type"] == "image_url"
    assert payload["image"]["url"].startswith("data:image/png;base64,")


def test_openai_edit_keeps_multipart_upload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = AIConfig(
        image_provider=AIProviderConfig(
            provider_type="openai",
            base_url="https://images.example.test/v1",
            api_key="test-key",
            model="gpt-image-2",
            enabled=True,
        ),
        image=AIImageConfig(size="1K", ratio="1:1", quality="standard", output_dir=str(tmp_path)),
    )
    module = AIImageModule(ModuleCard("ai_image", "AI Image", "", "ai", enabled=True), config, tmp_path)
    reference_path = tmp_path / "reference.png"
    reference_path.write_bytes(TINY_PNG)
    captured: list[object] = []

    def fake_urlopen(request: object, timeout: float) -> FakeHTTPResponse:
        captured.append(request)
        return FakeHTTPResponse({"data": [{"b64_json": base64.b64encode(TINY_PNG).decode("ascii")}]})

    monkeypatch.setattr("telegram_bot.modules.ai_image.urllib.request.urlopen", fake_urlopen)

    module._generate_image_with_openai_compatible_api("make it green", tmp_path / "edited.png", reference_path)

    request = captured[0]
    assert request.full_url == "https://images.example.test/v1/images/edits"
    assert request.get_header("Content-type").startswith("multipart/form-data; boundary=")
    assert b'name="size"' in request.data
    assert b"1024x1024" in request.data
    assert b'name="image"; filename="reference.png"' in request.data


def test_xai_imagine_2_quality_only_sends_supported_values() -> None:
    medium = build_xai_imagine_payload(
        model="grok-imagine-image-2.0",
        prompt="draw",
        size="1K",
        ratio="1:1",
        quality="medium",
    )
    high = build_xai_imagine_payload(
        model="grok-imagine-image-2.0",
        prompt="draw",
        size="1K",
        ratio="1:1",
        quality="high",
    )

    assert medium["quality"] == "medium"
    assert "quality" not in high


def test_xai_imagine_rejects_unsupported_4k_size(tmp_path: Path) -> None:
    config = AIConfig(
        image_provider=AIProviderConfig(
            provider_type="xai-imagine",
            base_url="https://images.example.test/v1",
            api_key="test-key",
            model="grok-imagine-image",
            enabled=True,
        ),
        image=AIImageConfig(size="4K", ratio="1:1", output_dir=str(tmp_path)),
    )
    module = AIImageModule(ModuleCard("ai_image", "AI Image", "", "ai", enabled=True), config, tmp_path)

    with pytest.raises(ValueError, match="1K.*2K"):
        module._generate_image_with_openai_compatible_api("draw a circle", tmp_path / "image.png")


def test_xai_config_error_is_shown_without_reference_fallback(tmp_path: Path) -> None:
    config = AIConfig(
        image_provider=AIProviderConfig(
            provider_type="xai-imagine",
            base_url="https://images.example.test/v1",
            api_key="test-key",
            model="grok-imagine-image",
            enabled=True,
        ),
        image=AIImageConfig(size="4K", ratio="1:1", output_dir=str(tmp_path)),
    )
    module = AIImageModule(ModuleCard("ai_image", "AI Image", "", "ai", enabled=True), config, tmp_path)
    reference_path = tmp_path / "reference.png"
    reference_path.write_bytes(TINY_PNG)

    async def fake_collect_context(message: object, prompt: str, replied: object) -> tuple[str, Path, str]:
        return prompt, reference_path, "引用图片"

    def unexpected_describe(*args: object) -> str:
        pytest.fail("configuration errors must not trigger reference-image fallback")

    module._collect_image_generation_context = fake_collect_context  # type: ignore[method-assign]
    module._call_ai_describe_reference_image = unexpected_describe  # type: ignore[method-assign]
    message = FakeMessage("/draw make it green")

    result = asyncio.run(module.handle_message(FakeEvent(message)))

    assert result.status == "handled"
    assert message.deleted is False
    assert any("配置错误" in edit and "1K 或 2K" in edit for edit in message.edits)
    assert reference_path.exists() is False


def test_xai_http_400_is_shown_instead_of_deleting_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = AIConfig(
        image_provider=AIProviderConfig(
            provider_type="xai-imagine",
            base_url="https://images.example.test/v1",
            api_key="test-key",
            model="grok-imagine-image-2.0",
            enabled=True,
        ),
        image=AIImageConfig(size="1K", ratio="auto", output_dir=str(tmp_path)),
    )
    module = AIImageModule(ModuleCard("ai_image", "AI Image", "", "ai", enabled=True), config, tmp_path)

    def fake_urlopen(request: object, timeout: float) -> FakeHTTPResponse:
        raise urllib.error.HTTPError(
            "https://images.example.test/v1/images/generations",
            400,
            "Bad Request",
            None,
            io.BytesIO(b'{"error":{"message":"xAI upstream returned status 400"}}'),
        )

    monkeypatch.setattr("telegram_bot.modules.ai_image.urllib.request.urlopen", fake_urlopen)
    message = FakeMessage("/draw a landscape")

    result = asyncio.run(module.handle_message(FakeEvent(message)))

    assert result.status == "handled"
    assert message.deleted is False
    assert any("请求失败" in edit and "HTTP 400" in edit and "内容审核" in edit for edit in message.edits)


def test_image_result_download_authenticates_same_origin_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: list[object] = []

    def fake_urlopen(request: object, timeout: float) -> FakeBytesResponse:
        captured.append(request)
        return FakeBytesResponse(TINY_PNG)

    monkeypatch.setattr("telegram_bot.modules.ai_image.urllib.request.urlopen", fake_urlopen)

    output = save_image_api_result(
        {"data": [{"url": "https://images.example.test/v1/files/result.png"}]},
        tmp_path / "result.png",
        30,
        api_key="secret-key",
        api_base_url="https://images.example.test/v1",
    )

    assert output.read_bytes() == TINY_PNG
    assert captured[0].get_header("Authorization") == "Bearer secret-key"
    assert captured[0].get_header("User-agent").startswith("Mozilla/5.0")


def test_image_result_download_does_not_leak_key_cross_origin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: list[object] = []

    def fake_urlopen(request: object, timeout: float) -> FakeBytesResponse:
        captured.append(request)
        return FakeBytesResponse(TINY_PNG)

    monkeypatch.setattr("telegram_bot.modules.ai_image.urllib.request.urlopen", fake_urlopen)

    save_image_api_result(
        {"data": [{"url": "https://cdn.example.test/result.png"}]},
        tmp_path / "result.png",
        30,
        api_key="secret-key",
        api_base_url="https://images.example.test/v1",
    )

    assert captured[0].get_header("Authorization") is None
    assert captured[0].get_header("User-agent").startswith("Mozilla/5.0")
