"""Full chat must execute the same local animation commands as quick chat."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from pet.app import _OverlayChatHost
from tests.test_quick_chat import _pump_until
from tests.test_quick_chat_actions import scene as scene
from tests.test_sprite_menu_facade import FakeClip
from tests.test_chat_window_lifecycle import _close


@pytest.fixture(params=["modern", "legacy"])
def full_chat(request, scene):
    shell, bubble, _network = scene
    if request.param == "modern":
        from pet.chat.widgets import ChatWindow
    else:
        from pet.chat.legacy_widgets import ChatWindow
    window = ChatWindow(bubble.config, "shenshen", pet_window=_OverlayChatHost(shell))
    window.service.provider = bubble.service.provider
    window.service.memory_extract_hook = None
    window.show()
    yield shell, window
    _close(window)


def submit(window, text):
    window.input.setPlainText(text)
    QTest.keyClick(window.input, Qt.Key.Key_Return)


def test_full_chat_return_key_actually_jumps(full_chat):
    shell, window = full_chat
    submit(window, "跳一跳")
    assert shell.host_for_sprite(shell.sprite).behavior.anim_of(shell.sprite) == "原地跳跃抓碎头顶物品"
    assert window.service.provider.calls == 0
    assert [(m.role, m.content) for m in window.session.messages][-2:] == [
        ("user", "跳一跳"), ("assistant", "收到，开始跳跃～")]
    assert window._active_request_id is None


def test_full_chat_spin_uses_visible_pet_even_without_optional_video(full_chat):
    shell, window = full_chat
    shell.sprite.library.acts = []
    submit(window, "转个圈")
    assert _pump_until(lambda: abs(shell.sprite.throw_rotation) > 1)
    assert window.service.provider.calls == 0
    assert _pump_until(lambda: not shell._golden_spin.active)


CORE = ["待机呼吸休闲", "东张西望", "螃蟹走路", "漂浮踏步", "左转奔跑",
        "被鼠标拖拽悬空反馈", "点击回应-开心跃动", "点击回应-傲娇生气",
        "点击回应-害羞惊讶", "点击回应-元气挥手", "点击回应-挠痒咯咯笑"]


@pytest.mark.parametrize("animation", CORE)
def test_every_installed_core_animation_can_be_requested(full_chat, animation):
    shell, window = full_chat
    lib = shell.sprite.library
    lib.idles = [CORE[0]]
    lib.turns = [CORE[1]]
    lib.moves = CORE[2:5]
    lib.drag = CORE[5]
    lib.clicks = CORE[6:]
    lib.acts = []
    for name in CORE:
        lib._clips[name] = FakeClip(name)
    shell.sprite.set_pos(QPointF(800, 300))
    submit(window, "播放动画 " + animation)
    assert "开始" in window.session.messages[-1].content
    behavior = shell.host_for_sprite(shell.sprite).behavior
    if animation not in lib.moves:
        assert behavior.anim_of(shell.sprite) == animation
    else:
        assert behavior.state_of(shell.sprite) in ("turn", "move")
    assert window.service.provider.calls == 0


@pytest.mark.parametrize("command,animation", [
    ("挥挥手", "点击回应-元气挥手"), ("害羞一下", "点击回应-害羞惊讶"),
    ("生个气", "点击回应-傲娇生气"), ("笑一笑", "点击回应-挠痒咯咯笑"),
])
def test_extra_friendly_commands_in_both_full_chat_styles(full_chat, command, animation):
    shell, window = full_chat
    lib = shell.sprite.library
    lib.clicks.append(animation)
    lib._clips[animation] = FakeClip(animation)
    submit(window, command)
    assert shell.host_for_sprite(shell.sprite).behavior.anim_of(shell.sprite) == animation
    assert window.service.provider.calls == 0


def test_action_list_only_advertises_available_assets(full_chat):
    shell, window = full_chat
    shell.sprite.library.acts = []
    submit(window, "动作列表")
    reply = window.session.messages[-1].content
    assert "转个圈" in reply and "播放动画 螃蟹走路" in reply
    assert "超大伸懒腰" not in reply
    assert window.service.provider.calls == 0
    body = window._bubbles[-1].body
    assert _pump_until(lambda: body.height() >= body.heightForWidth(body.width()) - 2), (
        body.height(), body.heightForWidth(body.width()))


def test_chat_host_does_not_retarget_to_a_replacement_pet(full_chat):
    shell, window = full_chat
    shell.exit_pet(shell.sprite)
    shell.spawn_pet()
    submit(window, "跳一下")
    assert "不可用" in window.session.messages[-1].content
    assert window.service.provider.calls == 0


class TextProvider:
    def __init__(self):
        self.calls = []

    def stream(self, messages, config, cancel):
        self.calls.append(messages)
        yield "正常聊天回复"


def test_ordinary_or_negated_chat_still_uses_the_provider(full_chat):
    shell, window = full_chat
    provider = TextProvider()
    window.service.provider = provider
    submit(window, "不要跳，聊聊天")
    assert _pump_until(lambda: window.session.messages[-1].role == "assistant")
    assert provider.calls and window.session.messages[-1].content == "正常聊天回复"
    assert shell.host_for_sprite(shell.sprite).behavior.anim_of(shell.sprite) != "原地跳跃抓碎头顶物品"


def test_modern_attachment_message_is_not_consumed_as_an_action(full_chat, tmp_path):
    shell, window = full_chat
    if not hasattr(window.composer, "attachment_paths"):
        pytest.skip("classic composer has no attachment support")
    provider = TextProvider()
    window.service.provider = provider
    attachment = tmp_path / "note.txt"
    attachment.write_text("attachment payload")
    window.composer.add_attachments([attachment])
    submit(window, "跳一下")
    assert _pump_until(lambda: window.session.messages[-1].role == "assistant")
    assert "note.txt" in window.session.messages[-2].content
    assert provider.calls and window.session.messages[-1].content == "正常聊天回复"
    assert shell.host_for_sprite(shell.sprite).behavior.anim_of(shell.sprite) != "原地跳跃抓碎头顶物品"


def test_pending_modern_typewriter_reply_is_saved_before_action(full_chat):
    _shell, window = full_chat
    if not hasattr(window, "_pending_finish_text"):
        pytest.skip("classic UI has no typewriter queue")
    window._pending_finish_text = "上一条完整回复"
    submit(window, "跳一下")
    assert [(m.role, m.content) for m in window.session.messages][-3:] == [
        ("assistant", "上一条完整回复"), ("user", "跳一下"), ("assistant", "收到，开始跳跃～")]
    assert window._pending_finish_text is None


@pytest.mark.parametrize("command", ["跑两步", "向右漂浮走几步", "螃蟹走几步", "播放动画 螃蟹走路"])
def test_all_movement_variants_respect_no_move(full_chat, command):
    shell, window = full_chat
    cfg = shell._sprite_config(shell.sprite)
    cfg.set("no_move", True)
    cfg.save()
    before = shell.sprite.pos
    submit(window, command)
    assert "不移动" in window.session.messages[-1].content
    assert shell.sprite.pos == before
    assert window.service.provider.calls == 0
