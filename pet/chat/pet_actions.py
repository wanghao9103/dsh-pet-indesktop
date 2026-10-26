"""Explicit quick-chat animation commands, resolved against the current pet's assets.

This channel consumes only a whole, positive command. Conversation, quotations,
negations and multi-step requests remain ordinary chat; model output is never
interpreted as an executable command.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Iterable


@dataclass(frozen=True)
class PetAction:
    kind: str
    direction: int | None = None


# Candidate order prefers the matching action; no unrelated random fallback.
_ANIMATIONS = {
    "jump": ("原地跳跃抓碎头顶物品", "点击回应 - 开心跃动"),
    "spin": ("小幅度原地 360 度旋转展示",),
    "dance": ("轻快摇摆舞", "可爱宅舞", "优雅女仆舞"),
    "stretch": ("超大伸懒腰",),
    "sleep": ("原地小憩沉眠",),
    "move": ("螃蟹走路", "漂浮踏步", "左转奔跑"),
}
_LABELS = {"jump": "跳跃", "spin": "转圈", "dance": "跳舞",
           "stretch": "伸懒腰", "sleep": "小憩", "move": "走动"}
_ADDRESS = re.compile(r"^(?:小肥鱼|大肥鱼|肥鱼|深深|小鲸鱼)[，,:：]?")
_POLITE = re.compile(r"^(?:(?:请你?|麻烦你?|能不能|可以|帮我|给我|你)){0,2}")
_RULES = tuple((kind, re.compile(pattern)) for kind, pattern in (
    ("jump", r"(?:跳(?:一下|一跳)?|跳跃(?:一下)?|蹦(?:一下|一蹦)?)"),
    ("spin", r"(?:转(?:个|一)?圈|转一转|转圈圈|旋转(?:一下|一圈)?)"),
    ("dance", r"(?:跳(?:个|一支|一段)?舞|跳舞一下)"),
    ("stretch", r"(?:伸(?:个|一(?:个)?)?懒腰|伸展一下)"),
    ("sleep", r"(?:睡(?:个|一)?觉|睡一下|小憩一下)"),
    ("move", r"(?:往|向|朝)?(?P<direction>左|右)?边?(?:走|移动|挪)(?:一下|一走|几步|两步|一步|一点)?"),
))


def parse_pet_action(text: str) -> PetAction | None:
    """Recognize short explicit commands without a model/API round trip."""
    if not text or len(text) > 96:
        return None
    text = re.sub(r"\s+", "", text).rstrip("吧呀啊嘛啦~～！!。.?？")
    text = _ADDRESS.sub("", text, count=1)
    text = _POLITE.sub("", text, count=1)
    for kind, pattern in _RULES:
        match = pattern.fullmatch(text)
        if match:
            direction = match.groupdict().get("direction")
            return PetAction(kind, {"左": -1, "右": 1}.get(direction))
    return None


def execute_pet_action(
    action: PetAction,
    names: Iterable[str],
    play: Callable[[str], bool],
    move: Callable[[str, int | None], bool],
    spin: Callable[[], bool] | None = None,
) -> str:
    """Return success feedback only when the addressed host accepts the action."""
    # Compact packs remove spaces from display/file names. Resolve to the
    # library's original key so both playback and movement classification agree.
    known = {re.sub(r"\s+", "", name): name for name in names}
    animation = next((known[re.sub(r"\s+", "", name)]
                      for name in _ANIMATIONS.get(action.kind, ())
                      if re.sub(r"\s+", "", name) in known), None)
    label = _LABELS.get(action.kind, "这个动作")
    if animation is None and action.kind == "spin" and spin is not None:
        accepted = spin()
    elif animation is None:
        return f"当前形象没有{label}动画，暂时做不了这个动作。"
    else:
        accepted = move(animation, action.direction) if action.kind == "move" else play(animation)
    if not accepted:
        return "暂时做不了这个动作：可能正在拖拽、飞行，或移动空间不足，请稍后再试。"
    if action.kind == "move" and action.direction is not None:
        label = "向左走" if action.direction < 0 else "向右走"
    return f"收到，开始{label}～"
