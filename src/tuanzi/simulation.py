"""10,000 场比赛模拟器。

负责批量运行比赛并统计各团子的获胜概率。
"""

import time
from collections import Counter
from pathlib import Path

# 项目根目录（src/tuanzi/simulation.py -> src/ -> 根目录）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

from src.tuanzi.game import Game


def run_simulations(
    num_games: int = 10_000,
    first_game: bool = False,
    group_index: int = 0,
):
    """运行 `num_games` 局比赛，返回 (胜场计数, 前4计数)。"""
    game = Game(group_index=group_index, first_game=first_game)
    wins: Counter = Counter()
    top4: Counter = Counter()

    start = time.perf_counter()
    report_interval = max(1, num_games // 20)

    for i in range(num_games):
        game.reset()
        winner = game.run()
        wins[winner] += 1

        for p in game.get_ranking()[:4]:
            top4[p.name] += 1

        if (i + 1) % report_interval == 0:
            pct = (i + 1) / num_games * 100
            elapsed = time.perf_counter() - start
            print(f"  [{pct:4.0f}%] {i + 1}/{num_games}  ({elapsed:.1f}s)")

    elapsed = time.perf_counter() - start
    print(f"\n完成 {num_games} 局模拟，耗时 {elapsed:.1f}s ({elapsed / num_games:.3f}s/局)")

    return dict(wins), dict(top4)


def print_results(wins: dict[str, int], top4: dict[str, int], total: int) -> None:
    """格式化输出获胜统计和前 4 率。"""
    lines = []
    lines.append(f"\n{'=' * 48}")
    lines.append(f"  「小团快跑」{total:,} 局模拟结果")
    lines.append(f"{'=' * 48}")

    # ── 胜率表 ──
    lines.append(f"  {'团子':<16s} {'胜场':>6s}  {'胜率':>8s}")
    lines.append(f"  {'-' * 34}")
    sorted_wins = sorted(wins.items(), key=lambda x: x[1], reverse=True)
    for name, count in sorted_wins:
        pct = count / total * 100
        bar_len = int(pct / 2)
        bar = "█" * bar_len
        lines.append(f"  {name:<16s} {count:>6d}  {pct:>6.2f}%  {bar}")
    lines.append(f"  {'-' * 34}")
    lines.append(f"  {'合计':<16s} {total:>6d}  {'100.00%':>8s}")

    # ── 前 4 率表 ──
    lines.append("")
    lines.append(f"  {'─' * 34}")
    lines.append(f"  {'团子':<16s} {'前4场':>6s}  {'前4率':>8s}")
    lines.append(f"  {'-' * 34}")
    sorted_top4 = sorted(top4.items(), key=lambda x: x[1], reverse=True)
    for name, count in sorted_top4:
        pct = count / total * 100
        bar_len = int(pct / 2)
        bar = "█" * bar_len
        lines.append(f"  {name:<16s} {count:>6d}  {pct:>6.2f}%  {bar}")

    lines.append(f"{'=' * 48}")

    text = "\n".join(lines)
    print(text)

    # 同时写入根目录 simulation_results.txt
    (_PROJECT_ROOT / "simulation_results.txt").write_text(text + "\n", encoding="utf-8")
