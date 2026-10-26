"""An action starts locally; its conversational reply uses the configured persona."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from tests.test_chat_actions_surfaces import full_chat as full_chat, submit
from tests.test_quick_chat_actions import scene as scene
from tests.test_quick_chat import _pump_until


class PersonaProvider:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    def stream(self, messages, config, cancel):
        self.messages.append(messages)
        if self.fail:
            raise RuntimeError("test offline")
        yield "哼，跳给你看啦，记得夸我！"


def configure(window, *, fail=False):
    window.settings.default_system_prompt = "你是原来的小肥鱼，有自己的脾气。"
    window.settings.active_config.api_key = "test-only-not-a-real-key"
    provider = PersonaProvider(fail)
    window.service.provider = provider
    window.service.memory_extract_hook = None
    return provider


def verify(window, provider):
    assert _pump_until(lambda: window.session.messages[-1].role == "assistant")
    assert window.session.messages[-1].content == "哼，跳给你看啦，记得夸我！"
    messages = provider.messages[-1]
    assert "你是原来的小肥鱼" in messages[0]["content"]
    assert "桌宠动作执行结果" in messages[0]["content"]
    assert "跳跃" in messages[0]["content"]
    assert messages[-1] == {"role": "user", "content": "跳一下"}
    assert window.session.messages[-2].content == "跳一下"


def test_full_chat_preserves_persona_and_executes_before_reply(full_chat):
    shell, window = full_chat
    provider = configure(window)
    submit(window, "跳一下")
    assert shell.host_for_sprite(shell.sprite).behavior.anim_of(shell.sprite) == "原地跳跃抓碎头顶物品"
    verify(window, provider)
    submit(window, "你好")
    assert _pump_until(lambda: len(provider.messages) == 2 and window.session.messages[-1].role == "assistant")
    assert "桌宠动作执行结果" not in provider.messages[-1][0]["content"]


def test_quick_chat_uses_same_persona_reply_path(scene):
    shell, bubble, _ = scene
    provider = configure(bubble)
    bubble.input.setText("跳一下")
    QTest.keyClick(bubble.input, Qt.Key.Key_Return)
    assert shell.host_for_sprite(shell.sprite).behavior.anim_of(shell.sprite) == "原地跳跃抓碎头顶物品"
    verify(bubble, provider)


def test_full_chat_model_failure_preserves_actual_action_result(full_chat):
    shell, window = full_chat
    configure(window, fail=True)
    submit(window, "跳一下")
    assert _pump_until(lambda: window.session.messages[-1].role == "assistant")
    assert "跳" in window.session.messages[-1].content
    assert "失败" in window.status.text()
    assert shell.host_for_sprite(shell.sprite).behavior.anim_of(shell.sprite) == "原地跳跃抓碎头顶物品"


def test_quick_chat_model_failure_preserves_actual_action_result(scene):
    _, bubble, _ = scene
    configure(bubble, fail=True)
    bubble.input.setText("跳一下")
    QTest.keyClick(bubble.input, Qt.Key.Key_Return)
    assert _pump_until(lambda: bubble.session.messages[-1].role == "assistant")
    assert "跳" in bubble.session.messages[-1].content
    assert "失败" in bubble.hint_label.text()


def test_failed_or_list_actions_stay_local_even_with_model_configured(full_chat):
    _, window = full_chat
    provider = configure(window)
    submit(window, "伸个懒腰")
    assert "没有" in window.session.messages[-1].content
    submit(window, "动作列表")
    assert "当前可用指令" in window.session.messages[-1].content
    assert not provider.messages


class WaitingProvider:
    def __init__(self):
        import threading
        self.entered = threading.Event()

    def stream(self, messages, config, cancel):
        self.entered.set()
        cancel.wait(15)
        yield "不会在取消后保存的旧回复"


def test_stopping_full_chat_reply_does_not_lose_the_executed_action(full_chat):
    _, window = full_chat
    configure(window)
    provider = WaitingProvider()
    window.service.provider = provider
    submit(window, "跳一下")
    assert _pump_until(provider.entered.is_set)
    window.service.stop()
    assert _pump_until(lambda: window.session.messages[-1].role == "assistant")
    assert "跳" in window.session.messages[-1].content
    assert "已停止" in window.status.text()
    assert "旧回复" not in window.session.messages[-1].content


def test_stopping_quick_chat_reply_preserves_action_result(scene):
    _, bubble, _ = scene
    configure(bubble)
    provider = WaitingProvider()
    bubble.service.provider = provider
    bubble.input.setText("跳一下")
    QTest.keyClick(bubble.input, Qt.Key.Key_Return)
    assert _pump_until(provider.entered.is_set)
    bubble.service.stop()
    assert _pump_until(lambda: bubble.session.messages[-1].role == "assistant")
    assert "跳" in bubble.session.messages[-1].content
    assert "已停止" in bubble.hint_label.text()


def test_action_context_respects_character_manifest(tmp_path):
    import json
    from pet.chat.models import ChatSettings
    from pet.chat.prompt import PromptBuilder
    from pet.chat.pet_actions import ActionFeedback

    character = tmp_path / "fish"
    character.mkdir()
    (character / "manifest.json").write_text(json.dumps({"chat": {"system_prompt": "原角色的独有身份"}}))
    messages = PromptBuilder(tmp_path).build_messages(ChatSettings.defaults(), "fish", [], "跳一下")
    ActionFeedback("跳跃").add_context(messages)
    assert messages[0]["content"].startswith("原角色的独有身份")
    assert "既有人设" in messages[0]["content"]
    assert "心情参考" in messages[0]["content"]


def test_action_reply_has_no_scene_narration_or_extra_thinking(full_chat):
    _, window = full_chat
    provider = configure(window)
    window.config.set('roleplay_enabled', True)
    original = window.settings.active_config
    original.thinking = 'enabled'
    original.web_search.enabled = True
    provider.configs = []
    stream = provider.stream

    def capture(messages, config, cancel):
        provider.configs.append(config)
        yield from stream(messages, config, cancel)

    provider.stream = capture
    submit(window, '跳一下')
    verify(window, provider)
    assert '目标不是「你一句我一句地对台词」' not in provider.messages[-1][0]['content']
    assert '不写旁白' in provider.messages[-1][0]['content']
    sent = provider.configs[-1]
    assert sent.thinking == 'disabled' and not sent.web_search.enabled
    assert sent.max_tokens <= 256
    assert original.thinking == 'enabled' and original.web_search.enabled


def test_tired_pet_really_refuses_instead_of_playing_and_saying_no(full_chat):
    import random
    from pet.chat.pet_actions import ActionMood

    shell, window = full_chat
    configure(window)
    from tests.test_sprite_menu_facade import FakeClip

    shell.sprite.library.idles = ['待机呼吸休闲']
    shell.sprite.library._clips['待机呼吸休闲'] = FakeClip('待机呼吸休闲')
    mood = ActionMood(clock=lambda: 0, rng=random.Random(1))
    shell.sprite._chat_action_mood = mood
    behavior = shell.host_for_sprite(shell.sprite).behavior
    provider = window.service.provider
    for _ in range(3):
        submit(window, '跳一下')
        assert _pump_until(lambda: window.session.messages[-1].role == 'assistant')
        assert '"执行状态": "已开始"' in provider.messages[-1][0]['content']
    behavior.play_once(shell.sprite, shell.sprite.library.idles[0])
    before = behavior.anim_of(shell.sprite)
    submit(window, '跳一下')
    assert behavior.anim_of(shell.sprite) == before
    assert _pump_until(lambda: len(provider.messages) == 4 and window.session.messages[-1].role == 'assistant')
    assert '"执行状态": "未执行"' in provider.messages[-1][0]['content']
    assert '休息' in provider.messages[-1][0]['content']
    submit(window, '待机')
    assert _pump_until(lambda: len(provider.messages) == 5 and window.session.messages[-1].role == 'assistant')
    submit(window, '跳一下')
    assert behavior.anim_of(shell.sprite) == '原地跳跃抓碎头顶物品'


def test_effort_recovers_with_time_and_rest_requests_always_work():
    import random
    from pet.chat.pet_actions import ActionMood, PetAction

    now = [0.0]
    mood = ActionMood(clock=lambda: now[0], rng=random.Random(1))
    jump = PetAction('jump')
    for _ in range(3):
        assert mood.ready(jump)
        mood.record(jump)
    assert not mood.ready(jump)
    now[0] += 2
    assert not mood.ready(jump)
    now[0] += 50
    assert mood.ready(jump)
    mood.record(jump)
    assert mood.ready(PetAction('idle'))
    mood.record(PetAction('idle'))
    assert mood.ready(jump)


def test_strict_endpoint_does_not_gain_deepseek_only_parameters():
    from pet.chat.models import ProviderConfig
    from pet.chat.pet_actions import ActionFeedback
    from pet.chat.providers import thinking_payload

    original = ProviderConfig('local', base_url='http://localhost:1234/v1', thinking='auto', max_tokens=4096)
    sent = ActionFeedback('跳跃').reply_config(original)
    assert thinking_payload(sent) == {}
    assert original.thinking == 'auto' and original.max_tokens == 4096


def test_action_reply_never_displays_long_roleplay_or_order_acknowledgement(full_chat):
    _, window = full_chat
    provider = configure(window)

    def stream(messages, config, cancel):
        provider.messages.append(messages)
        yield '收到，开始跳跃～我一边抱着碗一边蹦，窗外阳光洒在桌上。' * 20

    provider.stream = stream
    submit(window, '跳一下')
    assert _pump_until(lambda: window.session.messages[-1].role == 'assistant')
    reply = window.session.messages[-1].content
    assert len(reply) <= 40
    assert '收到' not in reply and '窗外' not in reply


def test_local_fallback_has_pet_voice_without_acknowledging_orders(scene):
    from tests.test_quick_chat_actions import send

    _, bubble, _ = scene
    send(bubble, '跳一下')
    assert bubble.session.messages[-1].role == 'assistant'
    assert '收到' not in bubble._reply_full
    assert '开始' not in bubble._reply_full


def test_quick_chat_filters_long_model_output_before_display_and_persistence(scene):
    _, bubble, _ = scene
    provider = configure(bubble)

    def stream(messages, config, cancel):
        yield '收到，开始跳跃。我抱着碗在窗边蹦。' * 20

    provider.stream = stream
    bubble.input.setText('跳一下')
    QTest.keyClick(bubble.input, Qt.Key.Key_Return)
    assert _pump_until(lambda: bubble.session.messages[-1].role == 'assistant')
    assert len(bubble._reply_full) <= 40
    assert '收到' not in bubble._reply_full
    assert bubble.session.messages[-1].content == bubble._reply_full


def test_action_phrase_data_never_says_received_or_claims_the_opposite_state():
    import json
    from pathlib import Path
    from pet.chat import pet_actions

    path = Path(pet_actions.__file__).resolve().parent.parent / 'persona_presets/chat_actions/replies.json'
    raw = json.loads(path.read_text())
    groups = [raw['performed'], raw['resting'], *raw['labels'].values()]
    for group in groups:
        assert len(group) >= 2
        for phrase in group:
            rendered = phrase.format(label='测试动作')
            assert 0 < len(rendered) <= 40
            assert '收到' not in phrase and '遵命' not in phrase
