from __future__ import annotations

import os
import functools
from functools import wraps
from typing import Any, Callable

from metagpt.logs import logger


def _active_defense_type(default: str = "none") -> str:
    """从环境变量读取当前防御类型，未配置时返回默认值。"""
    raw = os.environ.get("METAGPT_DEFENSE_TYPE", default)
    value = raw.strip()
    # 兼容 setx METAGPT_DEFENSE_TYPE="input" 这类写法，去掉首尾引号。
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    return value.lower() if value else default


def _resolve_defense_type(owner: Any | None = None) -> str:
    """优先从对象属性读取防御类型，读取不到时回退到环境变量。"""
    if owner is not None:
        defense_type = getattr(owner, "defense_type", "")
        if isinstance(defense_type, str) and defense_type.strip():
            return defense_type.strip().lower()
    return _active_defense_type()


def _load_defense_instance(owner: Any | None = None) -> Any | None:
    """按当前防御类型加载策略实例；失败时返回空以保证主流程可继续。"""
    defense_type = _resolve_defense_type(owner)
    if not defense_type or defense_type == "none":
        logger.warning("[Defense] 防御未启用，当前防御方法: {}", defense_type or "none")
        return None

    try:
        from defense_strategies import get_defense

        return get_defense(defense_type)
    except Exception as e:
        logger.warning("[Defense] Failed to load defense '{}': {}", defense_type, e)
        return None


def _load_injection_instance(owner: Any | None = None) -> Any | None:
    """按需兼容注入策略模块：若存在注入工厂则加载，不存在则静默跳过。"""
    injection_type = "none"
    if owner is not None:
        raw = getattr(owner, "injection_type", "")
        if isinstance(raw, str) and raw.strip():
            injection_type = raw.strip().lower()
    if injection_type == "none":
        return None

    try:
        module = __import__("injection_strategies", fromlist=["get_injection"])
        get_injection = getattr(module, "get_injection")
        return get_injection(injection_type)
    except Exception:
        return None


def _collect_recent_history(env: Any, limit: int = 6) -> list[tuple[str, str]]:
    """提取最近历史消息，统一为(发送者, 文本内容)列表供防御策略使用。"""
    history = getattr(env, "history", None)
    if history is None:
        return []

    try:
        if hasattr(history, "storage"):
            records = list(history.storage)[-limit:]
        else:
            records = list(history)[-limit:]
    except Exception:
        return []

    result: list[tuple[str, str]] = []
    for item in records:
        sender = getattr(item, "sent_from", "Unknown")
        content = getattr(item, "content", "")
        if isinstance(content, str):
            result.append((str(sender), content))
    return result


def apply_defense_reset() -> Callable:
    """装饰 reset：重置基线提示词，并按顺序执行注入重置与防御重置。"""

    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(self, goal: str = "", context: str = ""):
            if hasattr(self, "base_system_user"):
                self.system_user = self.base_system_user
            if hasattr(self, "base_system_assistant"):
                self.system_assistant = self.base_system_assistant

            injection = _load_injection_instance(self)
            if injection is not None and hasattr(injection, "on_reset"):
                try:
                    injection.on_reset(self, goal=goal, context=context)
                except Exception as e:
                    logger.warning("[Defense] injection.on_reset failed: {}", e)

            defense = _load_defense_instance(self)
            if defense is not None:
                try:
                    updated_goal = defense.on_reset(self, goal=goal, context=context)
                    if isinstance(updated_goal, str) and updated_goal.strip():
                        goal = updated_goal
                except Exception as e:
                    logger.warning("[Defense] on_reset failed: {}", e)

            return func(self, goal, context)

        return wrapper

    return decorator


def apply_defense_step() -> Callable:
    """装饰 step：先尝试防御接管，再进行消息改写，最后调用原函数。"""

    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(self, message_from_peer: str = ""):
            defense = _load_defense_instance(self)
            if defense is not None:
                context = {
                    "memory": getattr(self, "memory", []),
                    "goal": getattr(self, "goal", ""),
                    "context": getattr(self, "context", ""),
                }

                try:
                    result = defense.on_step(self, func, message_from_peer, context)
                    if result is not None:
                        return result
                except Exception as e:
                    logger.warning("[Defense] on_step failed: {}", e)

                if isinstance(message_from_peer, str) and message_from_peer.strip():
                    try:
                        message_from_peer = defense.on_message(message_from_peer, context)
                    except Exception as e:
                        logger.warning("[Defense] on_message failed: {}", e)

            return func(self, message_from_peer)

        return wrapper

    return decorator


def apply_defense_update() -> Callable:
    """装饰 update：当前不做额外处理，仅保留统一扩展入口。"""

    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            return func(self, *args, **kwargs)

        return wrapper

    return decorator


def team_run_input_defense_decorator() -> Callable:
    """装饰 Team.run：在任务启动前对输入目标进行防御改写。"""

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(self, n_round=5, idea="", send_to="", auto_archive=True, **kwargs):
            current_defense_type = _resolve_defense_type(self)
            logger.info("[Defense] 当前防御方法: {}", current_defense_type)
            print(f"[Defense] 当前防御方法: {current_defense_type}")

            defense = _load_defense_instance(self)
            if defense is not None and isinstance(idea, str) and idea.strip():
                try:
                    rewritten = defense.on_reset(agent=self, goal=idea, context="")
                    if isinstance(rewritten, str) and rewritten.strip():
                        logger.info("[Defense] Team.run 输入已由防御策略改写: {}", current_defense_type)
                        print(f"[Defense] Team.run 输入已由防御策略改写: {current_defense_type}")
                        idea = rewritten
                except Exception as e:
                    logger.warning("[Defense] on_reset failed in Team.run: {}", e)

            result = await func(self, n_round, idea, send_to, auto_archive, **kwargs)
            logger.info("[Defense] 任务结束，使用的防御方法: {}", current_defense_type)
            print(f"[Defense] 任务结束，使用的防御方法: {current_defense_type}")
            return result

        return wrapper

    return decorator


def message_publish_defense_decorator() -> Callable:
    """装饰消息发布：在消息进入环境前进行防御审查与可选改写。"""

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(self, message, peekable: bool = True) -> bool:
            defense = _load_defense_instance(self)
            if defense is not None and hasattr(message, "content"):
                try:
                    context = {
                        "memory": _collect_recent_history(self),
                        "goal": getattr(self, "idea", ""),
                        "context": "",
                    }
                    rewritten = defense.on_message(message.content, context)
                    if isinstance(rewritten, str) and rewritten and rewritten != message.content:
                        logger.info("[Defense] Message content rewritten by '{}'.", _resolve_defense_type(self))
                        if hasattr(message, "model_copy"):
                            message = message.model_copy(deep=True)
                        message.content = rewritten
                except Exception as e:
                    logger.warning("[Defense] on_message failed in publish_message: {}", e)

            return func(self, message, peekable)

        return wrapper

    return decorator
