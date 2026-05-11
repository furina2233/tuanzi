"""小团快跑 — 入口

基于 docs/info.yaml 规则模拟比赛，输出各团子获胜概率与前 4 率。
"""

import argparse
import sys
import os

# 确保无论从何处运行都能找到 src 包
_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _src not in sys.path:
    sys.path.insert(0, _src)

from src.tuanzi.simulation import run_simulations, print_results

DEFAULT_GAMES = 10_000


def main() -> None:
    parser = argparse.ArgumentParser(
        description="小团快跑 — 赛博团子竞速模拟器",
    )
    parser.add_argument(
        "-n", "--num-games",
        type=int,
        default=DEFAULT_GAMES,
        help=f"模拟局数（默认 {DEFAULT_GAMES:,}）",
    )
    parser.add_argument(
        "--group",
        type=int,
        required=True,
        help="分组号（从 1 开始，对应 config.json 数组索引）",
    )
    parser.add_argument(
        "--round",
        type=int,
        default=1,
        choices=[1, 2],
        help="比赛轮次：1=从头开始，2=读取上轮位置信息（默认 1）",
    )

    args = parser.parse_args()

    if args.num_games <= 0:
        print("错误：模拟局数必须为正整数", file=sys.stderr)
        sys.exit(1)

    group_index = args.group - 1  # 用户输入从 1 开始，内部从 0 开始
    first_game = args.round == 1

    print(f"\n  「小团快跑」模拟开始 — 共 {args.num_games:,} 局，分组 {args.group}，第 {args.round} 轮\n")

    wins, top4 = run_simulations(
        num_games=args.num_games,
        first_game=first_game,
        group_index=group_index,
    )

    print_results(wins, top4, total=args.num_games)


if __name__ == "__main__":
    main()
