"""
Tests for cross-platform audio/voice media routing.

These tests pin the expected delivery path for audio media files across
Telegram (where Bot-API sendAudio only accepts MP3/M4A and .ogg/.opus
only renders as a voice bubble when explicitly flagged) and via
``GatewayRunner._deliver_media_from_response``.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, MessageEvent, MessageType, SendResult
from gateway.run import GatewayRunner
from gateway.session import SessionSource, build_session_key


class _MediaRoutingAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(PlatformConfig(enabled=True, token="test"), Platform.TELEGRAM)

    async def connect(self):
        return True

    async def disconnect(self):
        pass

    async def send(self, chat_id, content=None, **kwargs):
        return SendResult(success=True, message_id="text")

    async def get_chat_info(self, chat_id):
        return {"id": chat_id, "type": "dm"}


def _routing_self():
    """Stub `self` for direct GatewayRunner._deliver_media_from_response calls.

    _deliver_media_from_response calls self._thread_metadata_for_source and
    self._reply_anchor_for_event. The tests assert on routing/dispatch only,
    so return a minimal metadata dict derived from the event's thread_id.
    """
    def _thread_meta(source, _anchor=None):
        tid = getattr(source, "thread_id", None)
        return {"thread_id": tid} if tid else None

    return SimpleNamespace(
        _thread_metadata_for_source=_thread_meta,
        _reply_anchor_for_event=lambda _event: None,
    )


def _event(thread_id=None):
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="chat-1",
        chat_type="dm",
        thread_id=thread_id,
    )
    return MessageEvent(
        text="make speech",
        message_type=MessageType.TEXT,
        source=source,
        message_id="msg-1",
    )


def _trusted_media_path(monkeypatch, tmp_path, name: str) -> str:
    path = tmp_path / name
    path.write_bytes(b"media")
    monkeypatch.setattr("gateway.platforms.base._trusted_gateway_media_roots", lambda: (tmp_path.resolve(),))
    return str(path)


@pytest.mark.asyncio
async def test_base_adapter_routes_telegram_flac_media_tag_to_document_sender(monkeypatch, tmp_path):
    adapter = _MediaRoutingAdapter()
    event = _event()
    media_path = _trusted_media_path(monkeypatch, tmp_path, "speech.flac")
    adapter._message_handler = AsyncMock(return_value=f"MEDIA:{media_path}")
    adapter.send_voice = AsyncMock(return_value=SendResult(success=True, message_id="voice"))
    adapter.send_document = AsyncMock(return_value=SendResult(success=True, message_id="doc"))

    await adapter._process_message_background(event, build_session_key(event.source))

    adapter.send_document.assert_awaited_once_with(
        chat_id="chat-1",
        file_path=media_path,
        metadata=None,
    )
    adapter.send_voice.assert_not_awaited()


@pytest.mark.asyncio
async def test_base_adapter_routes_non_voice_telegram_ogg_media_tag_to_document_sender(monkeypatch, tmp_path):
    adapter = _MediaRoutingAdapter()
    event = _event()
    media_path = _trusted_media_path(monkeypatch, tmp_path, "speech.ogg")
    adapter._message_handler = AsyncMock(return_value=f"MEDIA:{media_path}")
    adapter.send_voice = AsyncMock(return_value=SendResult(success=True, message_id="voice"))
    adapter.send_document = AsyncMock(return_value=SendResult(success=True, message_id="doc"))

    await adapter._process_message_background(event, build_session_key(event.source))

    adapter.send_document.assert_awaited_once_with(
        chat_id="chat-1",
        file_path=media_path,
        metadata=None,
    )
    adapter.send_voice.assert_not_awaited()


@pytest.mark.asyncio
async def test_base_adapter_routes_voice_tagged_telegram_ogg_media_tag_to_voice_sender(monkeypatch, tmp_path):
    adapter = _MediaRoutingAdapter()
    event = _event()
    media_path = _trusted_media_path(monkeypatch, tmp_path, "speech.ogg")
    adapter._message_handler = AsyncMock(
        return_value=f"[[audio_as_voice]]\nMEDIA:{media_path}"
    )
    adapter.send_voice = AsyncMock(return_value=SendResult(success=True, message_id="voice"))
    adapter.send_document = AsyncMock(return_value=SendResult(success=True, message_id="doc"))

    await adapter._process_message_background(event, build_session_key(event.source))

    adapter.send_voice.assert_awaited_once_with(
        chat_id="chat-1",
        audio_path=media_path,
        metadata=None,
    )
    adapter.send_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_streaming_delivery_routes_telegram_flac_media_tag_to_document_sender(monkeypatch, tmp_path):
    event = _event(thread_id="topic-1")
    media_path = _trusted_media_path(monkeypatch, tmp_path, "speech.flac")
    adapter = SimpleNamespace(
        name="test",
        extract_media=BasePlatformAdapter.extract_media,
        extract_images=BasePlatformAdapter.extract_images,
        extract_local_files=BasePlatformAdapter.extract_local_files,
        send_voice=AsyncMock(return_value=SendResult(success=True, message_id="voice")),
        send_document=AsyncMock(return_value=SendResult(success=True, message_id="doc")),
        send_image_file=AsyncMock(return_value=SendResult(success=True, message_id="image")),
        send_video=AsyncMock(return_value=SendResult(success=True, message_id="video")),
    )

    await GatewayRunner._deliver_media_from_response(
        _routing_self(),
        f"MEDIA:{media_path}",
        event,
        adapter,
    )

    adapter.send_document.assert_awaited_once_with(
        chat_id="chat-1",
        file_path=media_path,
        metadata={"thread_id": "topic-1"},
    )
    adapter.send_voice.assert_not_awaited()


@pytest.mark.asyncio
async def test_streaming_delivery_routes_non_voice_telegram_ogg_media_tag_to_document_sender(monkeypatch, tmp_path):
    event = _event(thread_id="topic-1")
    media_path = _trusted_media_path(monkeypatch, tmp_path, "speech.ogg")
    adapter = SimpleNamespace(
        name="test",
        extract_media=BasePlatformAdapter.extract_media,
        extract_images=BasePlatformAdapter.extract_images,
        extract_local_files=BasePlatformAdapter.extract_local_files,
        send_voice=AsyncMock(return_value=SendResult(success=True, message_id="voice")),
        send_document=AsyncMock(return_value=SendResult(success=True, message_id="doc")),
        send_image_file=AsyncMock(return_value=SendResult(success=True, message_id="image")),
        send_video=AsyncMock(return_value=SendResult(success=True, message_id="video")),
    )

    await GatewayRunner._deliver_media_from_response(
        _routing_self(),
        f"MEDIA:{media_path}",
        event,
        adapter,
    )

    adapter.send_document.assert_awaited_once_with(
        chat_id="chat-1",
        file_path=media_path,
        metadata={"thread_id": "topic-1"},
    )
    adapter.send_voice.assert_not_awaited()


@pytest.mark.asyncio
async def test_streaming_delivery_routes_telegram_mp3_media_tag_to_voice_sender(monkeypatch, tmp_path):
    """MP3 audio on Telegram must go through send_voice (which routes to
    sendAudio internally); Telegram accepts MP3 for the audio player."""
    event = _event(thread_id="topic-1")
    media_path = _trusted_media_path(monkeypatch, tmp_path, "speech.mp3")
    adapter = SimpleNamespace(
        name="test",
        extract_media=BasePlatformAdapter.extract_media,
        extract_images=BasePlatformAdapter.extract_images,
        extract_local_files=BasePlatformAdapter.extract_local_files,
        send_voice=AsyncMock(return_value=SendResult(success=True, message_id="voice")),
        send_document=AsyncMock(return_value=SendResult(success=True, message_id="doc")),
        send_image_file=AsyncMock(return_value=SendResult(success=True, message_id="image")),
        send_video=AsyncMock(return_value=SendResult(success=True, message_id="video")),
    )

    await GatewayRunner._deliver_media_from_response(
        _routing_self(),
        f"MEDIA:{media_path}",
        event,
        adapter,
    )

    adapter.send_voice.assert_awaited_once_with(
        chat_id="chat-1",
        audio_path=media_path,
        metadata={"thread_id": "topic-1"},
    )
    adapter.send_document.assert_not_awaited()
