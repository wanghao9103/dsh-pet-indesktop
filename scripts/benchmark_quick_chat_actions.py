"""Measure command parsing only; animation decode/rendering is not included."""
from __future__ import annotations

from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pet.chat.pet_actions import parse_pet_action  # noqa: E402


def main():
    samples = ["跳一下", "小肥鱼，请你转个圈吧！", "向右移动一下", "你好，今天怎么样？",
               "不要跳", "写个故事：小肥鱼跳一下", "跳一下" * 500]
    for text in samples:
        times = []
        for _ in range(7):
            start = time.perf_counter_ns()
            for _ in range(10_000):
                parse_pet_action(text)
            times.append((time.perf_counter_ns() - start) / 10_000 / 1000)
        print(f"chars={len(text):4d} median_us={statistics.median(times):.3f} "
              f"max_batch_us={max(times):.3f}")


if __name__ == "__main__":
    main()
