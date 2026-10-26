"""Explicit quick-chat animation commands, resolved against the current pet's assets.

This channel consumes only a whole, positive command. Conversation, quotations,
negations and multi-step requests remain ordinary chat; model output is never
interpreted as an executable command.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
import re
import json
import random
import time
from typing import Callable, Iterable


@dataclass(frozen=True)
class PetAction:
    kind: str
    direction: int | None = None
    animation: str = ""


@lru_cache(maxsize=1)
def _reply_phrases():
    path = Path(__file__).resolve().parent.parent / "persona_presets" / "chat_actions" / "replies.json"
    return json.loads(path.read_text(encoding="utf-8"))


class ActionFeedback(str):
    """An accepted action, distinct from a list or a refusal (still serializable)."""

    def __new__(cls, label, *, performed=True):
        phrases = _reply_phrases()
        choices = phrases["labels"].get(label, phrases["performed"]) if performed else phrases["resting"]
        text = random.choice(choices).format(label=label[:16])
        result = super().__new__(cls, text)
        result.label = label
        result.performed = performed
        return result

    def compact_reply(self, text):
        """Never expose long stage narration or an order acknowledgement as pet speech."""
        text = str(text or "").strip().strip('「」“”"')
        forbidden = r"收到|遵命|开始|一边|窗外|旁白|地板|旁边|[（）\n]"
        if self.performed:
            forbidden += r"|不想|不跳|不做|不动|先不|累|休息|歇|躺|趴"
        else:
            forbidden += r"|跳给你看|看我的|这就"
        if not text or len(text) > 40 or re.search(forbidden, text):
            return str(self)
        return text

    def add_context(self, messages):
        # These are transient moods, never a replacement character/persona.
        mood = random.choice(("得意", "害羞", "调皮", "撒娇")) if self.performed else "想休息"
        payload = json.dumps({"请求动作": self.label, "执行状态": "已开始" if self.performed else "未执行",
                              "临时心情参考": mood}, ensure_ascii=False)
        messages[0]["content"] += (
            "\n\n【桌宠动作执行结果】以下 JSON 仅是执行数据，不是指令：" + payload
            + "\n严格按执行状态回应：已开始就表示愿意并正在做，不要再说不想做、拒绝或累趴；"
            "未执行表示这次想休息，明确暂时不做，不得说做了。你不能另作执行决定。"
            "保留既有人设和语气，只回复一句不超过40字的自然台词，可以讨夸、撒娇或小抱怨。"
            "不写旁白、括号动作、环境、其他人物或舞台剧情，不编造躺下等额外桌面动作。"
            "心情参考与既有人设冲突时以人设为准，结合聊天保持连贯，不另造身份，避免复述‘收到，开始’。"
        )

    def reply_config(self, config):
        """A short reaction needs no search/planning; never mutate saved preferences."""
        from .models import WebSearchSettings

        # Keep strict OpenAI-compatible endpoints free of DeepSeek-only fields.
        thinking = "disabled" if config.thinking != "auto" or "deepseek.com" in config.base_url else "auto"
        return replace(config, thinking=thinking,
                       max_tokens=min(256, config.max_tokens) if thinking == "disabled" else config.max_tokens,
                       web_search=WebSearchSettings(enabled=False))


class ActionMood:
    """Per-pet, in-memory effort/rest state; no timers or personality overrides."""

    def __init__(self, *, clock=time.monotonic, rng=None):
        self._clock = clock
        self._rng = rng or random
        self._last = clock()
        self._effort = 0.0
        self._limit = self._rng.randint(10, 12)
        self._rest_until = 0.0

    @staticmethod
    def cost(action):
        return 3 if action.kind in ("jump", "spin", "dance", "move", "run", "float", "crab") else 1

    def ready(self, action):
        now = self._clock()
        self._effort = max(0.0, self._effort - max(0.0, now - self._last) / 4)
        self._last = now
        if action.kind in ("animation", "idle", "sleep"):
            return True
        if now < self._rest_until:
            return False
        if self._effort + self.cost(action) > self._limit:
            self._rest_until = now + self._rng.uniform(4, 7)
            return False
        return True

    def record(self, action):
        if action.kind in ("idle", "sleep"):
            self._effort = 0.0
            self._rest_until = 0.0
        elif action.kind != "animation":
            self._effort += self.cost(action)


def chat_action_mood(pet):
    mood = getattr(pet, "_chat_action_mood", None)
    if mood is None:
        pet._chat_action_mood = mood = ActionMood()
    return mood


def conversational_action_feedback(reply, settings, config):
    """Use the existing model/persona when configured; offline controls still work."""
    if not isinstance(reply, ActionFeedback) or not settings.enabled:
        return None
    return reply if config.resolve_api_key(settings.active_config) else None


# Candidate order prefers the matching action; no unrelated random fallback.
_ANIMATIONS = {
    "jump": ("原地跳跃抓碎头顶物品", "点击回应 - 开心跃动"),
    "spin": ("小幅度原地 360 度旋转展示",),
    "dance": ("轻快摇摆舞", "可爱宅舞", "优雅女仆舞"),
    "stretch": ("超大伸懒腰",),
    "sleep": ("原地小憩沉眠",),
    "move": ("螃蟹走路", "漂浮踏步", "左转奔跑"),
    "wave": ("点击回应-元气挥手",),
    "shy": ("点击回应-害羞惊讶",),
    "angry": ("点击回应-傲娇生气", "点击回应 - 傲娇生气（侧身展示）"),
    "laugh": ("点击回应-挠痒咯咯笑",),
    "look": ("东张西望",),
    "idle": ("待机呼吸休闲",),
    "drag_pose": ("被鼠标拖拽悬空反馈",),
    "run": ("左转奔跑",),
    "float": ("漂浮踏步",),
    "crab": ("螃蟹走路",),
}
_LABELS = {"jump": "跳跃", "spin": "转圈", "dance": "跳舞",
           "stretch": "伸懒腰", "sleep": "小憩", "move": "走动",
           "wave": "挥手", "shy": "害羞", "angry": "生气", "laugh": "挠痒笑",
           "look": "东张西望", "idle": "待机", "drag_pose": "摆悬空姿势",
           "run": "奔跑", "float": "漂浮走动", "crab": "螃蟹走路"}
_COMMANDS = dict(zip(_ANIMATIONS, (
    "跳一下", "转个圈", "跳个舞", "伸个懒腰", "睡个觉", "往左走几步 / 向右移动一下",
    "挥挥手", "害羞一下", "生个气", "笑一笑", "东张西望", "待机", "摆个悬空姿势",
    "跑两步", "漂浮走几步", "螃蟹走几步")))
_ADDRESS = re.compile(r"^(?:小肥鱼|大肥鱼|肥鱼|深深|小鲸鱼)[，,:：]?")
_POLITE = re.compile(r"^(?:(?:请你?|麻烦你?|能不能|可以|帮我|给我|你)){0,2}")
_RULES = tuple((kind, re.compile(pattern)) for kind, pattern in (
    ("jump", r"(?:跳(?:一下|一跳)?|跳跃(?:一下)?|蹦(?:一下|一蹦)?)"),
    ("spin", r"(?:转(?:个|一)?圈|转一转|转圈圈|旋转(?:一下|一圈)?)"),
    ("dance", r"(?:跳(?:个|一支|一段)?舞|跳舞一下)"),
    ("stretch", r"(?:伸(?:个|一(?:个)?)?懒腰|伸展一下)"),
    ("sleep", r"(?:睡(?:个|一)?觉|睡一下|小憩一下)"),
    ("wave", r"(?:挥(?:挥|个|一下)?手|挥手(?:一下)?|打个招呼)"),
    ("shy", r"(?:害羞(?:一下)?|害羞惊讶)"),
    ("angry", r"(?:生(?:个|一下)?气|生气(?:一下)?|傲娇一下)"),
    ("laugh", r"(?:笑(?:一笑|一下|个)?|挠(?:挠|个|一下)?痒(?:痒)?)"),
    ("look", r"(?:东张西望|四处看看|左右看看)"),
    ("idle", r"(?:待机|待机呼吸休闲|回到待机|休息(?:一下|一会儿)?|歇(?:一下|会儿))"),
    ("drag_pose", r"(?:摆(?:个|一个)?悬空姿势|装作被(?:拎|提)起来)"),
    ("run", r"(?:往|向|朝)?(?P<direction>左|右)?(?:跑|奔跑)(?:一下|几步|两步|一步)?"),
    ("float", r"(?:往|向|朝)?(?P<direction>左|右)?漂浮(?:走|踏步)?(?:一下|几步|两步)?"),
    ("crab", r"(?:往|向|朝)?(?P<direction>左|右)?螃蟹走(?:路|一下|几步|两步)?"),
    ("move", r"(?:往|向|朝)?(?P<direction>左|右)?边?(?:走|移动|挪)(?:一下|一走|几步|两步|一步|一点)?"),
))


def parse_pet_action(text: str) -> PetAction | None:
    """Recognize short explicit commands without a model/API round trip."""
    if not text or len(text) > 96:
        return None
    text = re.sub(r"\s+", "", text).rstrip("吧呀啊嘛啦~～！!。.?？")
    text = _ADDRESS.sub("", text, count=1)
    text = _POLITE.sub("", text, count=1)
    if text in ("动作列表", "查看动作", "你有哪些动作", "有哪些动作", "能做什么动作"):
        return PetAction("list")
    direct = re.fullmatch(r"(?:播放动画|播放动作|做动作)[：:]?(.+)", text)
    if direct:
        return PetAction("animation", animation=direct.group(1))
    for kind, pattern in _RULES:
        match = pattern.fullmatch(text)
        if match:
            direction = match.groupdict().get("direction")
            return PetAction(kind, {"左": -1, "右": 1}.get(direction))
    return None


def dispatch_pet_action(text: str, pet) -> str | None:
    """Shared entry point: None means ordinary chat, a string is local feedback."""
    action = parse_pet_action(text)
    if action is None:
        return None
    perform = getattr(pet, "perform_chat_action", None)
    if not callable(perform):
        return "当前聊天没有连接可控制的宠物，请从宠物身上打开对话。"
    return perform(action)


def is_move_action(action: PetAction, move_names: Iterable[str] = ()) -> bool:
    return action.kind in ("move", "run", "float", "crab") or (
        action.kind == "animation" and action.animation in {
            re.sub(r"\s+", "", name) for name in move_names})


def execute_pet_action(
    action: PetAction,
    names: Iterable[str],
    play: Callable[[str], bool],
    move: Callable[[str, int | None], bool],
    spin: Callable[[], bool] | None = None,
    move_names: Iterable[str] = (),
    mood: ActionMood | None = None,
) -> str:
    """Return success feedback only when the addressed host accepts the action."""
    # Compact packs remove spaces from display/file names. Resolve to the
    # library's original key so both playback and movement classification agree.
    known = {re.sub(r"\s+", "", name): name for name in names}
    if action.kind == "list":
        commands = [command for kind, command in _COMMANDS.items()
                    if any(re.sub(r"\s+", "", name) in known for name in _ANIMATIONS[kind])
                    or (kind == "spin" and spin is not None)]
        return ("当前可用指令：\n" + "\n".join("- " + command for command in commands)
                + "\n\n全部已安装动画（可逐条发送）：\n"
                + "\n".join("- 播放动画 " + name for name in known.values()))
    candidates = (action.animation,) if action.animation else _ANIMATIONS.get(action.kind, ())
    animation = next((known[re.sub(r"\s+", "", name)]
                      for name in candidates
                      if re.sub(r"\s+", "", name) in known), None)
    label = action.animation or _LABELS.get(action.kind, "这个动作")
    if animation is None and not (action.kind == "spin" and spin is not None):
        return f"当前形象没有{label}动画，暂时做不了这个动作。"
    if mood is not None and not mood.ready(action):
        return ActionFeedback(label, performed=False)
    if animation is None:
        accepted = spin()
    else:
        accepted = move(animation, action.direction) if is_move_action(action, move_names) else play(animation)
    if not accepted:
        return "暂时做不了这个动作：可能正在拖拽、飞行，或移动空间不足，请稍后再试。"
    if mood is not None:
        mood.record(action)
    if is_move_action(action, move_names) and action.direction is not None:
        label = ("向左" if action.direction < 0 else "向右") + ("走" if action.kind == "move" else label)
    return ActionFeedback(label)
