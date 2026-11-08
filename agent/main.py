#!/usr/bin/env python3
"""
AALC (AhabAssistantLimbusCompany) — MaaFramework Agent 服务端与 Android 原生 CLI 统一入口。

支持两种运行方式：
1. MaaFramework AgentServer 模式 (供 MaaFwApp Android APK / MaaPiCli 调用):
   `python3 agent/main.py <socket_id>`
2. Android Shizuku VirtualDisplay 独立 CLI 模式 (供 Termux 直接运行):
   `python3 agent/main.py --cli --task <task_type> [options]`
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# 确保工作目录与 sys.path 指向项目根目录，使 AALC 所有相对路径 (./assets/...) 100% 正常工作
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from module.logger.my_log import Logger

Logger()

from module.automation import auto
from module.automation.input_handlers.maa_control import MaaControl
from module.config import cfg
from module.logger import log
from tasks.base.back_init_menu import back_init_menu
from tasks.base.make_enkephalin_module import lunacy_to_enkephalin, make_enkephalin_module
from tasks.base.retry_monitor import retry_monitor
from tasks.base.script_task_scheme import (
    Buy_enkephalin,
    Mirror_task,
    ProductionModule_task,
     _batch_combat,
    init_game,
    onetime_EXP_process,
    onetime_thread_process,
    script_task,
    to_get_reward,
)
from utils.path_manager import path_manager


def _parse_sinner_order(order_str: str) -> list[int]:
    """
    将用户输入的罪人出战顺序字符串解析为 AALC 长度为 12 的 sinner_order 数组。
    支持两种格式：
    - 12 位完整序列，如 "1,2,3,4,5,6,7,8,9,10,11,12"
    - 按出战先后列出的罪人编号 (1~12)，如 "1,2,3,4,5,6,7"（表示罪人1第1顺位、罪人2第2顺位...）
    """
    parts = [int(x.strip()) for x in order_str.replace("，", ",").split(",") if x.strip().isdigit()]
    if len(parts) == 12 and set(parts) <= set(range(0, 13)):
        return parts
    sinner_order = [0] * 12
    rank = 1
    for sinner_idx in parts:
        if 1 <= sinner_idx <= 12 and sinner_order[sinner_idx - 1] == 0:
            sinner_order[sinner_idx - 1] = rank
            rank += 1
    if all(x == 0 for x in sinner_order):
        return list(range(1, 13))
    return sinner_order


def apply_config_overrides(overrides: dict[str, Any]) -> None:
    """将 MaaFramework interface.json (或 CLI) 传入的参数同步至 AALC 的 cfg 与 TeamSetting"""
    if not overrides:
        return

    log.info(f"正在应用任务配置覆盖: {overrides}")

    # 强制启用移动端 1080P 基准与触控寻路
    cfg.unsaved_set_value("simulator", True)
    cfg.unsaved_set_value("simulator_type", 2)
    cfg.unsaved_set_value("set_win_size", 1080)
    cfg.unsaved_set_value("mirror_keyboard_navigation", False)
    cfg.unsaved_set_value("mirror_keyboard_simple_pathfinding", False)
    cfg.unsaved_set_value("select_team_by_order", True)
    top_level_keys = [
        "daily_task",
        "set_EXP_count",
        "set_thread_count",
        "daily_teams",
        "use_continuous_combat",
        "use_continuous_combat_select",
        "targeted_teaming_EXP",
        "EXP_day_1_2",
        "EXP_day_3_4",
        "EXP_day_5_6",
        "EXP_day_7",
        "targeted_teaming_thread",
        "thread_day_1",
        "thread_day_2",
        "thread_day_3",
        "thread_day_4",
        "thread_day_5",
        "thread_day_6",
        "thread_day_7",
        "get_reward",
        "set_get_prize",
        "buy_enkephalin",
        "set_lunacy_to_enkephalin",
        "Dr_Grandet_mode",
        "skip_enkephalin",
        "mirror",
        "set_mirror_count",
        "hard_mirror",
        "auto_hard_mirror",
        "no_weekly_bonuses",
        "floor_3_exit",
        "infinite_dungeons",
        "save_rewards",
        "screenshot_interval",
        "mouse_action_interval",
        "task_stall_timeout",
        "skip_event_pack",
        "re_claim_rewards",
        "not_skip_whitegossypium",
        "fight_to_last_man",
        "select_team_by_order",
        "mirror_keyboard_navigation",
        "mirror_keyboard_simple_pathfinding",
        "screenshot_interval",
        "mouse_action_interval",
    ]

    for k in top_level_keys:
        if k in overrides and overrides[k] is not None:
            val = overrides[k]
            orig = cfg.get_value(k)
            if isinstance(orig, bool) and not isinstance(val, bool):
                if isinstance(val, str):
                    val = val.strip().lower() in ("true", "1", "yes")
                else:
                    val = bool(val)
            elif isinstance(orig, int) and not isinstance(orig, bool):
                try:
                    val = int(val)
                except (ValueError, TypeError):
                    pass
            elif isinstance(orig, float):
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    pass
            cfg.unsaved_set_value(k, val)

    # 镜牢队伍配置映射 (默认写入队伍 '1' 并确保其在激活队列中)
    team = cfg.config.teams.get("1")
    if team is not None:
        team_keys = [
            "team_system",
            "team_number",
            "shop_strategy",
            "do_not_heal",
            "do_not_buy",
            "do_not_fuse",
            "do_not_sell",
            "do_not_enhance",
            "only_aggressive_fuse",
            "do_not_system_fuse",
            "only_system_fuse",
            "avoid_skill_3",
            "prioritize_skill_3",
            "re_formation_each_floor",
            "normal_to_hard_floor",
            "use_starlight",
            "aggressive_also_enhance",
            "aggressive_save_systems",
            "defense_first_round",
            "defense_for_solo",
            "defense_for_solo_turns",
            "reward_cards",
            "reward_cards_select",
            "after_level_IV",
            "after_level_IV_select",
            "shopping_strategy",
            "shopping_strategy_select",
            "opening_items",
            "opening_items_select",
            "opening_items_system",
            "second_system",
            "second_system_select",
            "second_system_setting",
            "skill_replacement",
            "skill_replacement_select",
            "skill_replacement_mode",
            "max_keyword_refresh",
            "max_normal_refresh",
            "use_custom_theme_pack_weight",
            "use_team_code",
            "team_code",
        ]
        for tk in team_keys:
            if tk in overrides and overrides[tk] is not None:
                val = overrides[tk]
                orig = getattr(team, tk, None)
                if isinstance(orig, bool) and not isinstance(val, bool):
                    if isinstance(val, str):
                        val = val.strip().lower() in ("true", "1", "yes")
                    else:
                        val = bool(val)
                elif isinstance(orig, int) and not isinstance(orig, bool):
                    try:
                        val = int(val)
                    except (ValueError, TypeError):
                        pass
                setattr(team, tk, val)

        if "sinner_order_str" in overrides and overrides["sinner_order_str"]:
            order = _parse_sinner_order(str(overrides["sinner_order_str"]))
            team.sinner_order = order
            team.chosen_sinners = [1 if x > 0 else 0 for x in order]
            team.sinners_be_select = sum(team.chosen_sinners)
        elif all(x == 0 for x in team.sinner_order):
            # 若用户尚未配置罪人顺序，默认按 1~12 全选以防空编队卡死
            team.sinner_order = list(range(1, 13))
            team.chosen_sinners = [1] * 12
            team.sinners_be_select = 12

    if not cfg.teams_active_queue:
        if "opening_bonus_preset" in overrides and overrides["opening_bonus_preset"] is not None:
            preset_val = int(overrides["opening_bonus_preset"])
            team.opening_bonus = [preset_val] * 10
        cfg.set_team_enabled(1, True)
    else:
        cfg.save()


def execute_aalc_task(task_type: str, params: dict[str, Any]) -> bool:
    """根据 task_type 执行对应的完整 AALC 业务逻辑"""
    apply_config_overrides(params)

    if task_type == "full_script":
        script_task()
        return True

    if task_type == "start_and_home":
        init_game()
        path_manager.initialize_paths()
        auto.clear_img_cache()
        retry_monitor.start()
        try:
            ok = back_init_menu()
            if not cfg.skip_enkephalin:
                make_enkephalin_module()
            return bool(ok)
        finally:
            retry_monitor.stop()
            auto.clear_img_cache()

    if task_type == "enkephalin":
        init_game()
        path_manager.initialize_paths()
        auto.clear_img_cache()
        retry_monitor.start()
        try:
            back_init_menu()
            if cfg.buy_enkephalin and cfg.set_lunacy_to_enkephalin > 0:
                lunacy_to_enkephalin(times=cfg.set_lunacy_to_enkephalin)
            else:
                make_enkephalin_module(skip=False)
            return True
        finally:
            retry_monitor.stop()
            auto.clear_img_cache()

    if task_type == "exp_luxcavation":
        init_game()
        path_manager.initialize_paths()
        auto.clear_img_cache()
        retry_monitor.start()
        try:
            back_init_menu()
            make_enkephalin_module()
            exp_times = max(1, int(cfg.set_EXP_count or 1))
            if cfg.config.use_continuous_combat and cfg.use_continuous_combat_select > 0:
                _batch_combat(onetime_EXP_process, exp_times, cfg.use_continuous_combat_select)
            else:
                for _ in range(exp_times):
                    onetime_EXP_process()
            return True
        finally:
            retry_monitor.stop()
            auto.clear_img_cache()

    if task_type == "thread_luxcavation":
        init_game()
        path_manager.initialize_paths()
        auto.clear_img_cache()
        retry_monitor.start()
        try:
            back_init_menu()
            make_enkephalin_module()
            thread_times = max(1, int(cfg.set_thread_count or 1))
            if cfg.config.use_continuous_combat and cfg.use_continuous_combat_select > 0:
                _batch_combat(onetime_thread_process, thread_times, cfg.use_continuous_combat_select)
            else:
                for _ in range(thread_times):
                    onetime_thread_process()
            return True
        finally:
            retry_monitor.stop()
            auto.clear_img_cache()

    if task_type == "claim_rewards":
        init_game()
        path_manager.initialize_paths()
        auto.clear_img_cache()
        retry_monitor.start()
        try:
            to_get_reward()
            return True
        finally:
            retry_monitor.stop()
            auto.clear_img_cache()

    if task_type == "mirror_dungeon":
        init_game()
        path_manager.initialize_paths()
        auto.clear_img_cache()
        retry_monitor.start()
        try:
            Mirror_task()
            return True
        finally:
            retry_monitor.stop()
            auto.clear_img_cache()

    if task_type == "production_module_tool":
        return ProductionModule_task(
            kill_game_while_waiting=bool(params.get("tool_kill_game_waiting", False)),
            max_cycles=int(params.get("tool_production_cycles", 1)),
        )

    raise ValueError(f"未知的 AALC 任务类型: {task_type}")


def run_maa_agent_server(socket_id: str) -> None:
    """启动 MaaFramework AgentServer 并注册 AALC 自定义动作与识别算子"""
    from maa.agent.agent_server import AgentServer
    from maa.context import Context
    from maa.custom_action import CustomAction

    @AgentServer.custom_action("AALCRunTask")
    class AALCRunTaskAction(CustomAction):
        def run(self, context: Context, argv: CustomAction.RunArg) -> bool:
            try:
                MaaControl.bind_maa_context(context)
                auto.init_input()

                # 1. 读取 AALC_ConfigHolder 节点上的 attach 配置覆盖
                merged_params: dict[str, Any] = {}
                holder_data = context.get_node_data("AALC_ConfigHolder")
                if isinstance(holder_data, dict):
                    attach = holder_data.get("attach")
                    if isinstance(attach, dict):
                        merged_params.update(attach)

                # 2. 读取当前节点自身的 custom_action_param 与 attach
                node_data = context.get_node_data(argv.node_name)
                if isinstance(node_data, dict):
                    node_attach = node_data.get("attach")
                    if isinstance(node_attach, dict):
                        merged_params.update(node_attach)

                if argv.custom_action_param:
                    try:
                        act_param = json.loads(argv.custom_action_param)
                        if isinstance(act_param, dict):
                            merged_params.update(act_param)
                    except Exception:
                        pass

                task_type = merged_params.get("task_type", "full_script")
                log.info(f"[MaaAgent] 开始执行 AALC 任务: {task_type} (node={argv.node_name})")
                return execute_aalc_task(task_type, merged_params)
            except Exception as e:
                log.exception(f"[MaaAgent] 执行任务异常: {e}")
                return False

    log.info(f"[MaaAgent] 正在启动 AgentServer, socket_id={socket_id}")
    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()


def main() -> None:
    if len(sys.argv) >= 2 and not sys.argv[1].startswith("-"):
        # 标准 MaaFramework Agent 启动约定: 最后一位位置参数为 socket_id
        socket_id = sys.argv[-1]
        run_maa_agent_server(socket_id)
        return

    parser = argparse.ArgumentParser(description="AALC Android Native & MaaFramework Agent Runner")
    parser.add_argument("--cli", action="store_true", help="以独立 CLI 模式运行 (通过 Shizuku VirtualDisplay)")
    parser.add_argument(
        "--task",
        type=str,
        default="start_and_home",
        choices=[
            "full_script",
            "start_and_home",
            "enkephalin",
            "exp_luxcavation",
            "thread_luxcavation",
            "claim_rewards",
            "mirror_dungeon",
            "infinite_battle_tool",
            "production_module_tool",
        ],
        help="要执行的 AALC 任务类型",
    )
    parser.add_argument("--params", type=str, default="{}", help="JSON 格式的配置覆盖参数")
    parser.add_argument("--keep-vd", action="store_true", help="任务结束后保留虚拟副屏不销毁")
    args, unknown = parser.parse_known_args()

    if not args.cli and unknown:
        run_maa_agent_server(unknown[-1])
        return

    params = json.loads(args.params)
    ctrl = MaaControl()
    try:
        execute_aalc_task(args.task, params)
    finally:
        if not args.keep_vd:
            ctrl.stop_virtual_display()


if __name__ == "__main__":
    main()
