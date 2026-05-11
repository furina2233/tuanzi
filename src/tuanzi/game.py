"""小团快跑 - 游戏引擎

实现核心赛道、角色、技能、地图机制与比赛循环。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# 项目根目录（game.py → src/tuanzi/ → src/ → 根目录）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# --- 赛道常量 ---
TOTAL_STEPS = 32
PROPULSION_POSITIONS = {3, 11, 16, 23}   # 推进装置
BLOCKING_POSITIONS = {10, 28}             # 阻遏装置
RIFT_POSITIONS = {6, 20}                  # 时空裂隙
BU_DAWANG_START_ROUND = 3                 # 布大王登场轮次

CHARACTER_NAMES = [
    "陆·赫斯团子",
    "西格莉卡团子",
    "达妮娅团子",
    "绯雪团子",
    "卡提希娅团子",
    "菲比团子",
    "千咲团子",
    "莫宁团子",
    "琳奈团子",
    "爱弥斯团子",
    "守岸人团子",
    "珂莱塔团子",
]

# ---------------------------------------------------------------------------
#  日志
# ---------------------------------------------------------------------------

class GameLogger:
    """每局比赛的日志记录器。

    用法:
        logger = GameLogger()
        logger.log("掷骰: 6")
        logger.clear()         # 新局前清空
        logger.dump(file, 1)   # 写入文件对象
    """

    def __init__(self) -> None:
        self._lines: list[str] = []

    def log(self, msg: str) -> None:
        self._lines.append(msg)

    def clear(self) -> None:
        self._lines.clear()

    def dump(self, f, game_num: int) -> None:
        f.write(f"{'═' * 47}\n")
        f.write(f"  第 {game_num} 局\n")
        f.write(f"{'═' * 47}\n\n")
        for line in self._lines:
            f.write(line + "\n")
        f.write("\n")


@dataclass
class Player:
    """团子角色状态，包含所有技能所需的追踪字段。"""

    name: str
    position: int = 0

    # 达妮娅 — 连续性奖励
    prev_roll: Optional[int] = None

    # 绯雪 — 奇遇增益（是否遇过布大王）
    met_bu_dawang: bool = False

    # 卡提希娅 — 绝境逆袭
    desperate_used: bool = False       # 是否已触发过
    desperate_active: bool = False     # 是否处于逆袭状态

    # 西格莉卡 — 本回合被标记的罚退格数
    movement_penalty: int = 0

    # 上场掷骰是否发生了连续相同（给达妮娅用）
    # 用字段而非局部变量，避免在 turn 函数中传值复杂
    rolled_same_as_prev: bool = False

    # 是否必须先回到第 0 格（从 last_game.json 加载时使用）
    return_to_start: bool = False

    # 莫宁 — 点数循环计数器 (0→3, 1→2, 2→1)
    morning_cycle: int = 0

    # 爱弥斯 — 每场一次瞬移已用
    aimisi_used: bool = False

    def reset(self) -> None:
        self.position = 0
        self.prev_roll = None
        self.met_bu_dawang = False
        self.desperate_used = False
        self.desperate_active = False
        self.movement_penalty = 0
        self.rolled_same_as_prev = False
        self.return_to_start = False
        self.morning_cycle = 0
        self.aimisi_used = False


class Game:
    """单局比赛引擎。

    通过项目根目录 config.json 的指定分组加载出场团子和初始状态。

    用法:
        game = Game(group_index=0)
        winner_name = game.run()
    """

    def __init__(self, group_index: int = 0, first_game: bool = True) -> None:
        self._group_index = group_index

        # 加载 config.json
        config_path = _PROJECT_ROOT / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        group_config = config[group_index]

        # 出场团子中过滤掉「布大王」
        player_names = [n for n in group_config["出场团子"] if n != "布大王"]
        self.bu_dawang_enabled = "布大王" in group_config["出场团子"]

        self.players = [Player(name) for name in player_names]
        self._name_index = {p.name: p for p in self.players}

        # 行动顺序（每轮由预掷骰确定）
        self.turn_order: list[Player] = []

        # 布大王状态
        self.bu_dawang_position: int = TOTAL_STEPS  # 从终点出发
        self.bu_dawang_active: bool = False

        # 每格的堆叠结构：position → list[entity_name]（底 → 顶）
        # entity_name 可以是角色名或 "布大王"
        self.stacks: dict[int, list[str]] = {}

        self.round: int = 0
        self.winner: Optional[Player] = None

        # 日志记录器（由外部挂载，可选）
        self.logger: GameLogger | None = None

        # 加载上轮位置信息
        if not first_game:
            pos_data = group_config.get("上一轮结束时的位置信息", {})
            if pos_data:
                self._load_positions(pos_data)

    # ------------------------------------------------------------------
    #  内部日志辅助
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        if self.logger is not None:
            self.logger.log(msg)

    # ------------------------------------------------------------------
    #  公开 API
    # ------------------------------------------------------------------

    def run(self, save_state: bool = False) -> str:
        """完整运行一局，返回胜者名称。"""
        while self.winner is None:
            self._play_round()
        self._log(f">>> 胜者: {self.winner.name}")
        if save_state:
            self._save_last_game()
        return self.winner.name

    def reset(self) -> None:
        """重置整局状态，供下一局复用。"""
        for p in self.players:
            p.reset()
        self.turn_order.clear()
        self.round = 0
        self.winner = None
        self.bu_dawang_position = TOTAL_STEPS
        self.bu_dawang_active = False
        self.stacks.clear()

    # ------------------------------------------------------------------
    #  从 config 加载上轮位置信息
    # ------------------------------------------------------------------

    def _load_positions(self, data: dict) -> None:
        """从上次比赛的位置信息恢复状态。

        不在第 0 格的团子，本局需先回到第 0 格，再跑满 32 格。
        """
        if not data:
            return

        # 解析每个团子的位置和堆叠信息
        pos_info: dict[str, int] = {}
        above: dict[str, str] = {}
        below: dict[str, str] = {}

        for name, info in data.items():
            pos_info[name] = info["位置"]
            above[name] = info["上方团子"]
            below[name] = info["下方团子"]

        # 如果上方/下方引用了布大王但布大王不是 key，自动补齐
        if "布大王" not in pos_info:
            for name in list(above):
                if above[name] == "布大王" or below.get(name) == "布大王":
                    # 布大王和引用它的团子在同一个位置
                    pos = pos_info.get(name, 0)
                    pos_info["布大王"] = pos
                    above["布大王"] = ""
                    below["布大王"] = ""
                    break

        # 写入玩家位置 & 标记回起点模式
        for p in self.players:
            stored = pos_info.get(p.name, 0)
            if stored > 0:
                # 旧格式：直接存储了游戏内位置
                p.position = stored
                p.return_to_start = True
            elif stored < 0:
                # 新格式：负值 = 位置 - TOTAL_STEPS
                p.position = stored + TOTAL_STEPS
                p.return_to_start = True
            else:
                # stored == 0：已到达终点（新格式）或位于起点（旧/新格式）
                p.position = 0
                p.return_to_start = False

        # 布大王位置
        if "布大王" in pos_info:
            bd_stored = pos_info["布大王"]
            if bd_stored > 0:
                self.bu_dawang_position = max(0, min(TOTAL_STEPS, bd_stored))
            elif bd_stored < 0:
                self.bu_dawang_position = max(0, min(TOTAL_STEPS, bd_stored + TOTAL_STEPS))
            else:
                self.bu_dawang_position = TOTAL_STEPS

        # 重建堆叠结构：按位置分组，从底部（下方团子为空）开始链式构建
        by_pos: dict[int, list[str]] = {}
        for name, stored in pos_info.items():
            # 将存储位置转为游戏内位置（处理新旧两种格式）
            if stored > 0:
                game_pos = stored
            elif stored < 0:
                game_pos = stored + TOTAL_STEPS
            else:
                game_pos = 0
            by_pos.setdefault(game_pos, []).append(name)

        self.stacks.clear()
        for pos, names in by_pos.items():
            if len(names) == 1:
                self.stacks[pos] = names[:]
                continue
            # 找底部：下方团子为空的团子
            bottom = [n for n in names if below.get(n, "") == ""]
            if len(bottom) != 1:
                self.stacks[pos] = list(names)
                continue
            cur = bottom[0]
            stack = []
            seen = set()
            while cur and cur not in seen:
                seen.add(cur)
                stack.append(cur)
                cur = above.get(cur, "")
            self.stacks[pos] = stack

        # 确保布大王在堆叠底部（如果它在堆叠中）
        for pos, stack in self.stacks.items():
            if "布大王" in stack and stack[0] != "布大王":
                stack.remove("布大王")
                stack.insert(0, "布大王")

        self._log("读取上局存档：")
        for p in self.players:
            tag = " [需回第0格]" if p.return_to_start else ""
            self._log(f"  {p.name} 位置 {p.position}{tag}")
        if "布大王" in pos_info:
            self._log(f"  布大王 位置 {self.bu_dawang_position}")
        for pos, stack in self.stacks.items():
            if len(stack) > 1:
                self._log(f"  堆叠于位置 {pos}：{' ← '.join(stack)}")

        # 控制台输出上一局信息
        has_data = "布大王" in pos_info or any(pos_info.get(p.name, 0) != 0 for p in self.players)
        if has_data:
            print("\n上一轮比赛结果：")
            for p in self.players:
                stored = pos_info.get(p.name, 0)
                if stored == 0:
                    print(f"  {p.name}: 已完成")
                else:
                    print(f"  {p.name}: 位置 {stored}")
            if "布大王" in pos_info:
                print(f"  布大王: 位置 {pos_info['布大王']}")
            print()

    # ------------------------------------------------------------------
    #  写回 config.json
    # ------------------------------------------------------------------

    def _save_last_game(self) -> None:
        """将本局最终状态写入 config.json 对应分组的上一轮位置信息中。"""
        # 收集所有实体（玩家 + 布大王）
        entities = [p.name for p in self.players] + ["布大王"]

        above: dict[str, str] = {e: "" for e in entities}
        below: dict[str, str] = {e: "" for e in entities}

        for pos, stack in self.stacks.items():
            for i, name in enumerate(stack):
                if i > 0:
                    below[name] = stack[i - 1]
                if i < len(stack) - 1:
                    above[name] = stack[i + 1]

        data = {}
        for p in self.players:
            stored_pos = 0 if p.position >= TOTAL_STEPS else p.position - TOTAL_STEPS
            data[p.name] = {
                "位置": stored_pos,
                "上方团子": above[p.name],
                "下方团子": below[p.name],
            }

        # 更新 config.json 中对应分组的上一轮位置信息
        config_path = _PROJECT_ROOT / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config[self._group_index]["上一轮结束时的位置信息"] = data
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    #  回合循环
    # ------------------------------------------------------------------

    def _play_round(self) -> None:
        """执行一轮：掷骰定序 → 预分配移动点数 → 依次行动 → 布大王。"""
        self.round += 1

        self._log(f"\n── 第 {self.round} 轮 ──")

        # 清除上轮标记
        for p in self.players:
            p.movement_penalty = 0
            p.rolled_same_as_prev = False

        # ── 掷骰决定本回合行动顺序（与移动点数无关）──
        order_rolls: list[tuple[Player, int]] = []
        for p in self.players:
            if p.name == "守岸人团子":
                r = random.choice([2, 3])
            else:
                r = random.randint(1, 3)
            order_rolls.append((p, r))

        order_rolls.sort(key=lambda x: x[1], reverse=True)
        self.turn_order = [p for p, _ in order_rolls]

        roll_log = "  ".join(f"{p.name} {r}" for p, r in order_rolls)
        self._log(f"  行动顺序掷骰: {roll_log}")
        order_str = " → ".join(p.name for p in self.turn_order)
        self._log(f"  行动顺序: {order_str}")

        # ── 统一预分配本回合所有移动点数（含布大王）──
        self._pre_rolled_movement: dict[str, int] = {}
        for p in self.players:
            if p.name == "莫宁团子":
                cycle_values = [3, 2, 1]
                r = cycle_values[p.morning_cycle % 3]
                p.morning_cycle += 1
            elif p.name == "守岸人团子":
                r = random.choice([2, 3])
            else:
                r = random.randint(1, 3)

            # 达妮娅连续相同掷骰追踪
            if p.prev_roll is not None and r == p.prev_roll:
                p.rolled_same_as_prev = True
            p.prev_roll = r

            self._pre_rolled_movement[p.name] = r

        # 布大王预掷骰
        if self.bu_dawang_enabled:
            self._pre_rolled_movement["布大王"] = random.randint(1, 6)

        # ── 团子回合（按本轮点数决定的行动顺序）──
        for player in self.turn_order:
            if self.winner is not None:
                return
            self._player_turn(player)

        # ── 布大王回合（从第 BU_DAWANG_START_ROUND 轮开始）──
        if self.bu_dawang_enabled and self.round >= BU_DAWANG_START_ROUND:
            self.bu_dawang_active = True
            self._bu_dawang_turn()

        # 轮末检查布大王分离
        if self.bu_dawang_active:
            self._check_bu_dawang_separation()

    # ------------------------------------------------------------------
    #  团子回合
    # ------------------------------------------------------------------

    def _player_turn(self, player: Player) -> None:
        """处理一个团子的完整回合。"""
        self._log(f"\n【{player.name}】位置 {player.position}")

        # ── 读取预分配的本回合移动点数 ──
        roll = self._pre_rolled_movement[player.name]
        self._log(f"  移动点数: {roll}")

        # 1. 西格莉卡 — 投骰后标记紧邻的更高排名团子
        if player.name == "西格莉卡团子":
            self._apply_xigelika_mark(player)

        # 2. 计算基础移动力
        movement = roll

        # 3. 千咲 — 若投出本轮所有移动点数的最小值，额外前进 2 格
        move_values = [v for k, v in self._pre_rolled_movement.items() if k != "布大王"]
        min_move = min(move_values) if move_values else 1
        if player.name == "千咲团子" and roll == min_move:
            movement += 2
            self._log(f"  千咲技能：投出本轮最小值 {roll}！移动力 +2 → {movement}")

        # 4. 琳奈 — 60% 双倍 / 20% 无法移动
        if player.name == "琳奈团子":
            r_lin = random.random()
            if r_lin < 0.2:
                movement = 0
                self._log(f"  琳奈技能：本回合无法移动！")
            elif r_lin < 0.8:
                movement *= 2
                self._log(f"  琳奈技能：双倍移动！移动力 → {movement}")

        # 5. 珂莱塔 — 28% 概率双倍
        if player.name == "珂莱塔团子" and random.random() < 0.28:
            movement *= 2
            self._log(f"  珂莱塔技能：双倍移动！移动力 → {movement}")

        # 6. 扣除西格莉卡的罚退标记
        if player.movement_penalty > 0:
            reduction = min(player.movement_penalty, movement - 1)
            movement -= reduction
            player.movement_penalty -= reduction
            self._log(f"  西格莉卡罚退 -{reduction}，剩余移动力 {movement}")

        # 7. 达妮娅 — 连续性奖励
        if player.name == "达妮娅团子" and player.rolled_same_as_prev:
            movement += 2
            self._log(f"  达妮娅技能：连续相同掷骰！移动力 +2 → {movement}")

        # 8. 菲比 — 50% 概率冲刺 +1
        if player.name == "菲比团子" and random.random() < 0.5:
            movement += 1
            self._log(f"  菲比技能：冲刺！移动力 +1 → {movement}")

        # 9. 绯雪 — 遇布大王后每轮 +1
        if player.name == "绯雪团子" and player.met_bu_dawang:
            movement += 1
            self._log(f"  绯雪技能：布大王奇遇增益！移动力 +1 → {movement}")

        # 10. 卡提希娅 — 绝境逆袭 60% 概率 +2
        if player.name == "卡提希娅团子" and player.desperate_active:
            if random.random() < 0.6:
                movement += 2
                self._log(f"  卡提希娅技能：绝境逆袭！移动力 +2 → {movement}")
            else:
                self._log(f"  卡提希娅技能：绝境逆袭发动失败")

        # 11. 执行移动
        old_pos = player.position

        if player.return_to_start:
            # ⬅️ 回起点模式：向后移动
            player.position -= movement
            self._log(f"  回起点移动: {old_pos} → {player.position}")

            if player.position <= 0:
                player.position = 0
                player.return_to_start = False
                self._log(f"  ✓ 回到第 0 格！下一轮开始正常前进")

            # 更新堆叠（带动上方团子一起移动）
            self._update_stacking(player.name, old_pos, player.position)

            # 回起点途中不触发地图装置、不检查相遇/技能
            # 卡提希娅技能检查（回起点也可能处于最后一名）
            self._check_desperate(player)

            self._log(f"  最终位置: {player.position}")
            return

        # ➡️ 正常向前移动
        player.position += movement
        self._log(f"  移动: {old_pos} → {player.position}")

        # 碰线获胜：堆叠最上方团子获胜
        if player.position >= TOTAL_STEPS:
            player.position = TOTAL_STEPS
            self._update_stacking(player.name, old_pos, player.position)
            winner_name = self.stacks.get(TOTAL_STEPS, [player.name])[-1]
            self.winner = self._name_index.get(winner_name, player)
            return

        # 不低于起点
        if player.position < 0:
            player.position = 0

        # 12. 更新堆叠（带动上方团子一起移动）
        self._update_stacking(player.name, old_pos, player.position)

        # 13. 触发地图装置（可能再次移动，内部会处理堆叠更新）
        device_moved = self._trigger_map_device(player)
        if device_moved:
            if player.position >= TOTAL_STEPS:
                player.position = TOTAL_STEPS
                winner_name = self.stacks.get(TOTAL_STEPS, [player.name])[-1]
                self.winner = self._name_index.get(winner_name, player)
                return
            if player.position < 0:
                player.position = 0

        # 14. 爱弥斯 — 经过中点后传送到前方最近团子顶端（每场一次）
        if (player.name == "爱弥斯团子" and not player.aimisi_used
                and player.position > TOTAL_STEPS // 2):
            ahead = [p for p in self.players
                     if p.name != player.name and p.position > player.position]
            if ahead:
                target = min(ahead, key=lambda p: p.position)
                self._log(f"  爱弥斯技能：传送到 {target.name}（{target.position}）顶端！")
                old_pos = player.position
                player.position = target.position
                player.aimisi_used = True
                self._update_stacking(player.name, old_pos, player.position)

        self._log(f"  最终位置: {player.position}")

        # 15. 检查是否与布大王相遇（绯雪条件）
        if self.bu_dawang_active and player.position == self.bu_dawang_position:
            player.met_bu_dawang = True
            self._log(f"  ★ 与布大王相遇于位置 {player.position}！")

        # 16. 卡提希娅 — 移动结束时检查是否最后一名
        self._check_desperate(player)

    # ------------------------------------------------------------------
    #  卡提希娅技能辅助
    # ------------------------------------------------------------------

    def _check_desperate(self, player: Player) -> None:
        if player.name == "卡提希娅团子" and not player.desperate_used:
            if self._get_rank(player) == len(self.players) - 1:
                player.desperate_used = True
                player.desperate_active = True
                self._log(f"  ★ 绝境逆袭激活！（排名最后）")

    # ------------------------------------------------------------------
    #  布大王
    # ------------------------------------------------------------------

    def _bu_dawang_turn(self) -> None:
        """布大王：从终点向起点移动，逐格更新堆叠，受赛道机制影响。"""
        roll = self._pre_rolled_movement.get("布大王", random.randint(1, 6))
        start_pos = self.bu_dawang_position

        self._log(f"\n【布大王】位置 {start_pos}")
        self._log(f"  掷骰: {roll}")

        # 逐格移动，每格更新堆叠（带动上方团子）
        for _ in range(roll):
            if self.bu_dawang_position <= 0:
                break
            step_old = self.bu_dawang_position
            self.bu_dawang_position -= 1
            self._log(f"  移动: {step_old} → {self.bu_dawang_position}")
            self._update_stacking("布大王", step_old, self.bu_dawang_position)

        if self.bu_dawang_position < 0:
            self.bu_dawang_position = 0

        # 布大王受地图装置影响（"受赛道机制影响"）
        self._trigger_map_device_for_bu_dawang()

        # 布大王落地后，检查是否有团子在同一格——触发"相遇"
        self._check_bu_dawang_meet_players()

    def _check_bu_dawang_meet_players(self) -> None:
        """布大王移动到某格后，检查该格是否有团子，触发相遇效果。"""
        pos = self.bu_dawang_position
        if pos in self.stacks:
            met = [p.name for p in self.players
                   if p.name in self.stacks.get(pos, []) and p.name != "布大王"]
            if met:
                for p in self.players:
                    if p.name in self.stacks.get(pos, []):
                        p.met_bu_dawang = True
                self._log(f"  ★ 布大王与 {'、'.join(met)} 相遇于位置 {pos}！")

    def _check_bu_dawang_separation(self) -> None:
        """轮末检查：若布大王与最后一名团子不在同格，传送回终点，终点成为新起点。"""
        last_player = self._get_last_place_player()
        if self.bu_dawang_position != last_player.position:
            self._log(f"  ◇ 布大王与最后一名({last_player.name})分离，传送回终点")
            old_pos = self.bu_dawang_position
            self.bu_dawang_position = TOTAL_STEPS
            self._update_stacking("布大王", old_pos, self.bu_dawang_position)

    # ------------------------------------------------------------------
    #  排名
    # ------------------------------------------------------------------

    def get_ranking(self) -> list[Player]:
        """按位置降序排列（位置高 = 排名靠前）。"""
        return sorted(self.players, key=lambda p: p.position, reverse=True)

    def _get_rank(self, player: Player) -> int:
        """返回 0-based 排名（0 = 第1名）。"""
        ranking = self.get_ranking()
        try:
            return ranking.index(player)
        except ValueError:
            return len(self.players) - 1

    def _get_last_place_player(self) -> Player:
        """返回当前最后一名的团子。"""
        return min(self.players, key=lambda p: p.position)

    # ------------------------------------------------------------------
    #  西格莉卡技能
    # ------------------------------------------------------------------

    def _apply_xigelika_mark(self, player: Player) -> None:
        """西格莉卡：标记排名紧邻且更高的至多两个团子。"""
        ranking = self.get_ranking()
        idx = ranking.index(player)

        # "排名更高" = 排名数字更小（位置更高）
        # "紧邻自身" = 排名表中紧挨着自己之前
        # "至多两个" = 最多标记 2 个
        start = max(0, idx - 2)
        targets = ranking[start:idx]

        if targets:
            names = "、".join(p.name for p in targets)
            self._log(f"  西格莉卡技能：标记 {names}（罚退 +{len(targets)}）")

        for p in targets:
            # 每标记叠加一次罚退
            p.movement_penalty += 1

    # ------------------------------------------------------------------
    #  堆叠
    # ------------------------------------------------------------------

    def _update_stacking(self, entity_name: str, old_pos: int, new_pos: int) -> None:
        """实体移动后更新堆叠结构。

        规则:
        - 团子移动时，带动其上方（堆叠中更高层的）所有团子一起移动，下方的不动
        - 布大王也遵循此规则，因始终在底部，移动时带动上方所有团子
        - 添加到目标格时置于堆叠最上方；布大王始终在底部
        - 首轮比赛时，行动顺序决定堆叠顺序（行动越靠前、越在上方），不带动上方团子
        """
        # ── 首轮：不带动上方团子，先行动的在上方 ──
        if self.round == 1:
            self._remove_from_stacks(entity_name, position=old_pos)
            if new_pos not in self.stacks:
                self.stacks[new_pos] = [entity_name]
            else:
                # 插入到底部，使先行动的团子保持在上方
                self.stacks[new_pos].insert(0, entity_name)
            # 确保布大王仍在底部
            if "布大王" in self.stacks[new_pos]:
                buf = self.stacks[new_pos]
                buf.remove("布大王")
                buf.insert(0, "布大王")
            return

        # ── 普通团子：查找旧堆叠中的位置 ──
        old_stack = self.stacks.get(old_pos, [])
        if entity_name not in old_stack:
            # 异常情况：直接移除并添加
            self._remove_from_stacks(entity_name, position=old_pos)
            self._add_to_stack(entity_name, new_pos)
            return

        idx = old_stack.index(entity_name)
        moving = old_stack[idx:]    # 自身 + 上方所有团子
        staying = old_stack[:idx]   # 下方团子不动

        # 更新被带动团子的 position
        for name in moving:
            if name == entity_name:
                continue
            carried = self._name_index.get(name)
            if carried is not None:
                carried.position = new_pos
                # 布大王带动时，被携带的团子视为与布大王相遇
                if entity_name == "布大王":
                    carried.met_bu_dawang = True
                self._log(f"  ↑ {name} 被带动至位置 {new_pos}")

        # 旧堆叠保留下方部分
        if staying:
            self.stacks[old_pos] = staying
        else:
            self.stacks.pop(old_pos, None)

        # 加入新堆叠（置于顶部）
        if new_pos not in self.stacks:
            self.stacks[new_pos] = []
        self.stacks[new_pos].extend(moving)

        # 如果目标格已有布大王，确保其仍在底部
        if "布大王" in self.stacks[new_pos]:
            buf = self.stacks[new_pos]
            buf.remove("布大王")
            buf.insert(0, "布大王")

    def _add_to_stack(self, entity_name: str, pos: int) -> None:
        """将实体添加到指定格的堆叠顶部。"""
        if pos not in self.stacks:
            self.stacks[pos] = []
        self.stacks[pos].append(entity_name)

    def _remove_from_stacks(self, entity_name: str, position: int | None = None) -> None:
        """将实体从堆叠中移除（可选限定位置）。"""
        for pos, stack in list(self.stacks.items()):
            if position is not None and pos != position:
                continue
            if entity_name in stack:
                stack.remove(entity_name)
                if not stack:
                    del self.stacks[pos]
                return

    # ------------------------------------------------------------------
    #  地图装置
    # ------------------------------------------------------------------

    def _trigger_map_device(self, player: Player) -> bool:
        """团子落点触发地图装置，返回是否产生了额外移动。"""
        pos = player.position

        if pos in PROPULSION_POSITIONS:
            extra = 1                       # 基础 +1
            skill_tag = ""
            if player.name == "陆·赫斯团子":
                extra = 4                   # 技能：额外 +3，共 +4
                skill_tag = " [陆·赫斯团子技能]"
            new_pos = pos + extra
            player.position = new_pos
            self._update_stacking(player.name, pos, new_pos)
            self._log(f"  ◆ 推进装置触发于位置 {pos}！前进至 {new_pos}（+{extra}）{skill_tag}")
            return True

        if pos in BLOCKING_POSITIONS:
            penalty = 1                     # 基础 -1
            skill_tag = ""
            if player.name == "陆·赫斯团子":
                penalty = 2                 # 技能：额外 -1，共 -2
                skill_tag = " [陆·赫斯团子技能]"
            new_pos = max(0, pos - penalty)
            player.position = new_pos
            self._update_stacking(player.name, pos, new_pos)
            self._log(f"  ◆ 阻遏装置触发于位置 {pos}！后退至 {new_pos}（-{penalty}）{skill_tag}")
            return True

        if pos in RIFT_POSITIONS:
            if pos in self.stacks and len(self.stacks[pos]) > 1:
                self._trigger_rift(pos)
            else:
                self._log(f"  ◆ 时空裂隙于位置 {pos}，但无其他实体，无效果")

        return False

    def _trigger_map_device_for_bu_dawang(self) -> None:
        """布大王受地图装置影响。"""
        pos = self.bu_dawang_position

        if pos in PROPULSION_POSITIONS:
            new_pos = min(TOTAL_STEPS, pos + 1)
            self.bu_dawang_position = new_pos
            self._update_stacking("布大王", pos, new_pos)
            self._log(f"  ◆ 布大王触发推进装置！前进至 {new_pos}（+1）")
            return

        if pos in BLOCKING_POSITIONS:
            new_pos = max(0, pos - 1)
            self.bu_dawang_position = new_pos
            self._update_stacking("布大王", pos, new_pos)
            self._log(f"  ◆ 布大王触发阻遏装置！后退至 {new_pos}（-1）")
            return

        if pos in RIFT_POSITIONS:
            if pos in self.stacks and len(self.stacks[pos]) > 1:
                self._trigger_rift(pos)

    def _trigger_rift(self, pos: int) -> None:
        """时空裂隙：随机重组堆叠顺序，布大王保持在底部。"""
        stack = self.stacks[pos]
        # 分离布大王
        has_bu = "布大王" in stack
        if has_bu:
            stack.remove("布大王")

        # 随机打乱其余实体
        random.shuffle(stack)

        # 布大王重新放回底部
        if has_bu:
            stack.insert(0, "布大王")

        self._log(f"  ◆ 时空裂隙于位置 {pos}！堆叠顺序重排")
