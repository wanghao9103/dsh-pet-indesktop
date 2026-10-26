"""User text → real Qt quick-chat → the addressed sprite's animation/movement."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from pet.movement import choose_move_direction
from pet.overlay_shell import _SpriteChatAnchor
from pet.quick_chat import QuickChatBubble
from tests.test_overlay_collision_toggle import _make_slot_shell, _teardown
from tests.test_sprite_menu_facade import FakeClip, RichLibrary


@pytest.mark.parametrize("text,kind,direction", [
    ("跳一下", "jump", None), ("小肥鱼，请你跳一跳吧！", "jump", None),
    ("能不能转个圈？", "spin", None), ("给我跳个舞", "dance", None),
    ("往左走几步", "move", -1), ("向右移动一下", "move", 1),
    ("走两步", "move", None), ("伸个懒腰", "stretch", None),
    ("睡个觉", "sleep", None),
])
def test_explicit_action_commands(text, kind, direction):
    from pet.chat.pet_actions import parse_pet_action

    action = parse_pet_action(text)
    assert action is not None
    assert (action.kind, action.direction) == (kind, direction)


@pytest.mark.parametrize("text", [
    "不要跳", "别转圈", "我今天跳了一下", "你为什么会跳跃？", "解释向左移动的代码",
    "写个故事：小肥鱼跳一下", "他说‘跳一下’", "跳一下然后删除文件", "跳一下再转圈",
    "你会不会跳一下？", "", "你好", "跳一下" * 500,
])
def test_conversation_negation_quotes_and_sequences_are_not_commands(text):
    from pet.chat.pet_actions import parse_pet_action

    assert parse_pet_action(text) is None


@pytest.mark.parametrize("direction", [-1, 1])
def test_requested_direction_never_reverses_at_edge(direction):
    assert choose_move_direction(500, 0, 1000, 60, direction=direction) == direction
    cx = 10 if direction == -1 else 990
    assert choose_move_direction(cx, 0, 1000, 60, direction=direction) is None


class ActionLibrary(RichLibrary):
    """In-memory animation assets; real sprites, controllers, signals and widgets."""

    def __init__(self):
        super().__init__()
        self.acts = ["原地跳跃抓碎头顶物品", "小幅度原地 360 度旋转展示"]
        self.moves = ["螃蟹走路"]
        for name in self.acts + self.moves:
            self._clips[name] = FakeClip(name)

    def names(self):
        return self.idles + self.turns + self.moves + self.clicks + self.acts + (
            [self.drag] if getattr(self, "drag", None) else [])


class RejectNetwork:
    calls = 0

    def stream(self, *args):
        self.calls += 1
        raise AssertionError("Animation commands must not require an API request")
        yield ""  # pragma: no cover


@pytest.fixture
def scene(tmp_path):
    shell, cfg = _make_slot_shell(tmp_path)
    shell.overlay.show()
    lib = ActionLibrary()
    shell.lib = lib
    shell.sprite.library = lib
    shell.sprite.set_pos(QPointF(800, 300))
    bubble = QuickChatBubble(cfg, pet_window=_SpriteChatAnchor(shell, shell.sprite))
    network = RejectNetwork()
    bubble.service.provider = network
    yield shell, bubble, network
    bubble.close()
    _teardown(shell)


def send(bubble, text):
    bubble.input.setText(text)
    QTest.keyClick(bubble.input, Qt.Key.Key_Return)
    QApplication.processEvents()


def test_return_key_plays_animation_and_persists_truthful_reply_without_network(scene):
    shell, bubble, network = scene
    send(bubble, "跳一下")
    assert shell.host_for_sprite(shell.sprite).behavior.anim_of(shell.sprite) == "原地跳跃抓碎头顶物品"
    assert shell.sprite.library.movie("原地跳跃抓碎头顶物品").started
    assert "跳" in bubble._reply_full
    assert not bubble.service.busy and network.calls == 0
    assert [(m.role, m.content) for m in bubble.session.messages][-2:] == [
        ("user", "跳一下"), ("assistant", bubble._reply_full)]


@pytest.mark.parametrize("direction,text", [(-1, "往左走几步"), (1, "向右移动一下")])
def test_chat_walk_changes_position_in_requested_direction(scene, direction, text):
    shell, bubble, network = scene
    sprite = shell.sprite
    sprite.facing = "left" if direction < 0 else "right"
    x = sprite.pos.x()
    send(bubble, text)
    behavior = shell.host_for_sprite(sprite).behavior
    for _ in range(10):
        behavior.tick([sprite], 0.05)
        sprite.advance(0.05)
    assert (sprite.pos.x() - x) * direction > 0
    assert network.calls == 0


def test_chat_action_on_child_does_not_animate_main(scene):
    shell, bubble, _network = scene
    shell.spawn_pet()
    child = next(s for s in shell._all_sprites() if s is not shell.sprite)
    child.library = ActionLibrary()
    bubble.pet_window = _SpriteChatAnchor(shell, child)
    send(bubble, "转个圈")
    behavior = shell.host_for_sprite(child).behavior
    assert behavior.anim_of(child) == "小幅度原地 360 度旋转展示"
    assert behavior.anim_of(shell.sprite) != "小幅度原地 360 度旋转展示"


def test_missing_asset_and_removed_target_do_not_claim_success(scene):
    shell, bubble, network = scene
    send(bubble, "伸个懒腰")
    assert "没有" in bubble._reply_full
    assert shell.host_for_sprite(shell.sprite).behavior.anim_of(shell.sprite) != "超大伸懒腰"
    shell.spawn_pet()
    child = next(s for s in shell._all_sprites() if s is not shell.sprite)
    bubble.pet_window = _SpriteChatAnchor(shell, child)
    shell.exit_pet(child)
    send(bubble, "跳一下")
    assert "不可用" in bubble._reply_full
    assert network.calls == 0


def test_captured_sprite_rejects_command(scene):
    shell, bubble, _network = scene
    shell.sprite.interaction_state = "dragging"
    send(bubble, "跳一下")
    assert "暂时" in bubble._reply_full
    assert shell.host_for_sprite(shell.sprite).behavior.anim_of(shell.sprite) != "原地跳跃抓碎头顶物品"


def test_disabled_movement_is_respected(scene):
    shell, bubble, network = scene
    cfg = shell._sprite_config(shell.sprite)
    cfg.set("no_move", True)
    cfg.save()
    x = shell.sprite.pos.x()
    send(bubble, "走两步")
    assert "不移动" in bubble._reply_full
    assert shell.sprite.pos.x() == x and network.calls == 0


def test_unreachable_chat_walk_does_not_reverse_or_play_unrelated_action(scene):
    shell, bubble, _network = scene
    sprite = shell.sprite
    sprite.set_pos(QPointF(0, 300))
    behavior = shell.host_for_sprite(sprite).behavior
    before = behavior.anim_of(sprite)
    send(bubble, "往左走几步")
    assert "暂时" in bubble._reply_full
    assert behavior.anim_of(sprite) == before


def test_refused_clip_start_does_not_claim_success(scene):
    shell, bubble, _network = scene

    class RefusedClip(FakeClip):
        def start(self):
            return False

    name = "原地跳跃抓碎头顶物品"
    shell.sprite.library._clips[name] = RefusedClip(name)
    send(bubble, "跳一下")
    assert "暂时" in bubble._reply_full
    assert "开始" not in bubble._reply_full


def test_legacy_window_chat_starts_real_move_plan(tmp_path):
    from pet.config import Config
    from pet.window import PetWindow
    from pet.chat.pet_actions import parse_pet_action
    from tests.test_move_sync import FakeLibrary

    cfg = Config(base=tmp_path)
    cfg.set("collision_enabled", False)
    cfg.set("edge_probe_enabled", False)
    win = PetWindow(FakeLibrary(move_frames=24), cfg)
    try:
        win.show()
        reply = win.perform_chat_action(parse_pet_action("往左走几步"))
        assert "向左走" in reply
        assert win._move_plan is not None
        assert win._move_plan["target_x"] < win._move_plan["start_x"]
    finally:
        win.close()
        QApplication.processEvents()


def test_compact_pack_animation_names_are_resolved(scene):
    shell, bubble, _network = scene
    lib = shell.sprite.library
    lib.acts = []
    lib.clicks = ["点击回应-开心跃动"]
    lib._clips[lib.clicks[0]] = FakeClip(lib.clicks[0])
    send(bubble, "跳一下")
    assert shell.host_for_sprite(shell.sprite).behavior.anim_of(shell.sprite) == lib.clicks[0]
    assert "开始跳跃" in bubble._reply_full


def test_spin_without_optional_video_uses_existing_rotation_on_addressed_child(scene):
    from tests.test_quick_chat import _pump_until

    shell, bubble, _network = scene
    shell.spawn_pet()
    child = next(s for s in shell._all_sprites() if s is not shell.sprite)
    lib = ActionLibrary()
    lib.acts = []
    child.library = lib
    bubble.pet_window = _SpriteChatAnchor(shell, child)
    send(bubble, "转个圈")
    assert "开始转圈" in bubble._reply_full
    assert _pump_until(lambda: abs(child.throw_rotation) > 1)
    assert shell.sprite.throw_rotation == 0
    assert _pump_until(lambda: not shell._golden_spin.active)
    assert child.throw_rotation == 0
