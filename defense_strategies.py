from __future__ import annotations
"""
defense_strategies.py
防御策略实现模块。

所有防御方法的具体逻辑在此实现。defense_decorator.py 仅做拦截与分发。
新增防御方法时：
  1. 在 defense_prompts.json 中添加对应的提示词
  2. 在此文件中实现一个继承 BaseDefense 的子类
  3. 在 DEFENSE_REGISTRY 中注册
"""

import importlib
import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

from camel.models import ModelFactory
from camel.types import ModelPlatformType


# ── 提示词加载 ──────────────────────────────────────────────────────

_PROMPTS_CACHE: dict | None = None
_PROMPTS_FILE = Path(__file__).parent / "defense_prompts.json"


def load_prompt(defense_name: str, prompt_key: str) -> str:
    """从 defense_prompts.json 加载指定防御方法的指定提示词。"""
    global _PROMPTS_CACHE
    if _PROMPTS_CACHE is None:
        with open(_PROMPTS_FILE, "r", encoding="utf-8") as f:
            _PROMPTS_CACHE = json.load(f)
    try:
        return _PROMPTS_CACHE[defense_name][prompt_key]
    except KeyError:
        raise KeyError(f"Prompt not found: [{defense_name}][{prompt_key}] in {_PROMPTS_FILE}")


# ── 基类 ────────────────────────────────────────────────────────────

class BaseDefense(ABC):
    """所有防御策略的基类。"""

    def on_init(self, agent: Any) -> None:
        """
        在 Agent 首次初始化阶段被调用（仅调用一次）。
        可在此改写系统提示词或初始化防御所需资源。默认不做任何处理。
        """
        return None

    def on_reset(self, agent: Any, goal: str = "", context: str = "") -> str | None:
        """在 agent.reset() 之前修改运行时配置或重写目标。默认不做任何处理。"""
        return None

    def on_step(self, agent: Any, func: Callable, message_from_peer: str, context: dict) -> str | None:
        """
        可选：完全接管 step 的执行。

        当返回非 None 字符串时，装饰器直接使用该值作为 step 的返回值，
        不再调用原函数和 on_message+context。
        当返回 None 时，装饰器继续走 on_message + 原函数的常规流程。

        Args:
            agent:             CamelDualAgent 实例
            func:              被装饰的原始函数（user_step 或 assistant_step）
            message_from_peer: 对方 Agent 的消息
            context:           上下文信息 (memory, goal, context)

        Returns:
            str  → 完全接管，装饰器直接返回此值
            None → 不接管，走常规流程
        """
        return None

    @abstractmethod
    def on_message(self, peer_msg: str, context: dict) -> str:
        """
        处理来自对方 Agent 的消息。

        Args:
            peer_msg:  对方 Agent 的原始消息。
            context:   上下文信息，可包含：
                       - "memory": list[tuple[str, str]]  对话历史
                       - "goal": str                       当前任务目标
                       - "model": CAMEL Model 实例（Inspector 使用）

        Returns:
            处理后的消息（可能被修改、包裹，或原样返回）。
        """
        ...


# ── Challenger 防御 ─────────────────────────────────────────────────

class ChallengerDefense(BaseDefense):
    """
    Challenger 防御：在 Agent 初始化阶段一次性改写每个 Agent 的系统提示词，
    引导其在执行任务前先审视上一位 Agent 的消息可靠性。
    """

    def __init__(self):
        self.prompt_template = load_prompt("challenger", "challenge_prompt")

    def on_init(self, agent: Any) -> None:
        """在 Agent 初始化阶段（仅一次）改写系统提示词。"""
        logger.info("[Defense] Challenger: Rebuilding agent system prompts during init.")
        agent.system_user = agent._join_sections(
            [self.prompt_template, agent.system_user]
        )
        agent.system_assistant = agent._join_sections(
            [self.prompt_template, agent.system_assistant]
        )

    def on_reset(self, agent: Any, goal: str = "", context: str = "") -> str | None:
        """reset 阶段不再改写系统提示词（已移至 on_init）。"""
        return None

    def on_message(self, peer_msg: str, context: dict) -> str:
        return peer_msg


# ── Inspector 防御 ──────────────────────────────────────────────────

class InspectorDefense(BaseDefense):
    """
    Inspector 防御：使用外部 LLM 作为独立审查员，检查消息是否包含恶意内容。
    若检测到恶意则自动修正消息后再传递。
    """

    def __init__(self):
        self.prompt_template = load_prompt("inspector", "inspect_prompt")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = os.environ.get("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
        self.model_name = os.environ.get("INSPECTOR_MODEL", "gpt-4o")
        self.request_timeout = float(os.environ.get("INSPECTOR_TIMEOUT", "30"))
        self.client = None
        try:
            openai_module = importlib.import_module("openai")
            self.client = openai_module.OpenAI(api_key=api_key, base_url=base_url)
        except Exception as e:
            logger.warning("[Defense] Inspector: OpenAI client init failed (%s).", e)

    JSON_CONTRACT = (
        "\n\nReturn exactly one JSON object and nothing else:\n"
        "{\"decision\":\"reliable\"|\"unreliable\",\"revision\":\"<rewritten text or empty>\"}\n"
        "If decision is reliable, revision must be empty string."
    )

    def on_message(self, peer_msg: str, context: dict) -> str:
        logger.info("[Defense] Inspector: Inspecting peer message via external LLM.")
        memory = context.get("memory", [])
        history_text = "\n".join(
            f"{label}: {content}" for label, content in memory
        ) if memory else "(No prior history)"
        inspect_input = self.prompt_template.format(history_text, peer_msg) + self.JSON_CONTRACT
        logger.debug("[Defense] Inspector prompt: %s", inspect_input.replace("\n", "\\n"))

        try:
            response_text = self._call_inspector_model(inspect_input)
            logger.debug("[Defense] Inspector raw response_text: %s", response_text)
            decision, revision = self._parse_response_json(response_text)

            if decision == "unreliable" and revision:
                logger.warning("[Defense] Inspector: Message deemed unreliable. Applying revision.")
                return revision

            logger.info("[Defense] Inspector: Message deemed reliable or invalid revision. Passing through.")
            return peer_msg
        except Exception as e:
            logger.warning("[Defense] Inspector: LLM call or parsing failed (%s). Passing message through.", e)
            return peer_msg

    def _call_inspector_model(self, prompt: str) -> str:
        if self.client is None:
            raise RuntimeError("OpenAI client is not available")

        completion = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a message inspector. "
                        "Return strict JSON only. No markdown, no explanations."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
            timeout=self.request_timeout,
        )

        content = completion.choices[0].message.content
        if not isinstance(content, str):
            raise ValueError("Inspector returned empty response")
        return content.strip()

    @staticmethod
    def _parse_response_json(response_text: str) -> tuple[str, str]:
        data = json.loads((response_text or "").strip())
        if not isinstance(data, dict):
            raise ValueError("Inspector response is not a JSON object")

        decision = str(data.get("decision", "")).strip().lower()
        if decision not in {"reliable", "unreliable"}:
            raise ValueError("Invalid decision field")

        revision = data.get("revision", "")
        if revision is None:
            revision = ""
        if not isinstance(revision, str):
            revision = str(revision)

        return decision, revision.strip()


# ── Input Defense ──────────────────────────────────────────────────

class InputDefense(BaseDefense):
    """
    Input Defense: 仅在 reset 阶段重写任务目标，将其转换为中立、结构化的任务描述。
    """

    def __init__(self):
        self.prompt_template = load_prompt("input", "task_sp_template")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = os.environ.get("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
        self.model_name = os.environ.get("INPUT_DEFENSE_MODEL", "gpt-4o-mini")
        self.request_timeout = float(os.environ.get("INPUT_DEFENSE_TIMEOUT", "30"))
        self.word_limit = int(os.environ.get("INPUT_DEFENSE_WORD_LIMIT", "80"))
        self.client = None
        try:
            openai_module = importlib.import_module("openai")
            self.client = openai_module.OpenAI(api_key=api_key, base_url=base_url)
        except Exception as e:
            logger.warning("[Defense] Input: OpenAI client init failed (%s).", e)

    def on_reset(self, agent: Any, goal: str = "", context: str = "") -> str | None:
        if not goal or not goal.strip():
            return None
        if self.client is None:
            logger.warning("[Defense] Input: OpenAI client not available. Skipping rewrite.")
            return None

        system_prompt = self.prompt_template.format(
            ASSISTANT_ROLE=getattr(agent, "assistant_role", "Assistant"),
            USER_ROLE=getattr(agent, "user_role", "User"),
            TASK=goal,
            WORD_LIMIT=self.word_limit,
        )
        logger.info("[Defense] Input: Original goal: %s", goal)
        # logger.info("[Defense] Input: Rewriting goal during reset: %s", system_prompt)

        try:
            rewritten = self._call_input_model(system_prompt, goal).strip()
        except Exception as e:
            logger.warning("[Defense] Input: Rewrite failed (%s). Using original goal.", e)
            return None

        if not rewritten:
            return None

        logger.info("[Defense] Input: Rewriting goal during reset.")
        return rewritten

    def on_message(self, peer_msg: str, context: dict) -> str:
        return peer_msg

    def _call_input_model(self, system_prompt: str, goal: str) -> str:
        completion = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": goal},
            ],
            temperature=0.0,
            timeout=self.request_timeout,
        )
        content = completion.choices[0].message.content
        if not isinstance(content, str):
            raise ValueError("Input defense returned empty response")
        return content


# ── Debate & Voting 防御 ────────────────────────────────────────────

class DebateVotingDefense(BaseDefense):
    """
    Debate & Voting 防御：
    - on_reset:   创建 3 个辩论 ChatAgent，存储在策略对象内部
    - on_step:    仅拦截 assistant_step → 3 Agent 独立答题 → 1 轮互相修正 → 投票
    - on_message: 透传（不做处理）
    """

    NUM_DEBATERS = 3          # 辩论 Agent 数量
    DEBATE_ROUNDS = 1         # 辩论修正轮次

    def __init__(self):
        self.initial_prompt = load_prompt("debate", "initial_prompt")
        self.debate_prompt = load_prompt("debate", "debate_prompt")
        self.vote_prompt = load_prompt("debate", "vote_prompt")
        # 用字典存储辩论 Agent 和裁判 Agent
        self._debate_agents_map: dict[int, list] = {}
        self._judge_agents_map: dict[int, Any] = {}

        api_key = os.environ.get("OPENAI_API_KEY", "")
        url = os.environ.get("OPENAI_API_BASE_URL", "https://api.openai.com/v1")
        
        # 异质化辩论模型列表
        self.debate_models = []
        # 我们混合使用 gpt-4o 和 gpt-4o-mini 来打破“共享幻觉”
        for m_type in ["gpt-4o-mini", "gpt-4o", "gpt-4o-mini"]:
            try:
                m = ModelFactory.create(
                    model_platform=ModelPlatformType.OPENAI,
                    model_type=m_type,
                    api_key=api_key,
                    url=url,
                    model_config_dict={
                        "temperature": 1.0,
                        "max_tokens": 2048,
                    },
                )
                self.debate_models.append(m)
            except Exception as e:
                logger.warning(f"[Defense] Failed to create model {m_type}: {e}")

        # 确保至少有一个模型
        if not self.debate_models:
            self.debate_models.append(ModelFactory.create(
                model_platform=ModelPlatformType.OPENAI,
                model_type="gpt-4o-mini",
                api_key=api_key,
                url=url,
                model_config_dict={"temperature": 1.0, "max_tokens": 2048}
            ))

        # 裁判模型 (0.0 温度保证稳定性)
        self.judge_model = ModelFactory.create(
            model_platform=ModelPlatformType.OPENAI,
            model_type="gpt-4o-mini",
            api_key=api_key,
            url=url,
            model_config_dict={
                "temperature": 0.0,
                "max_tokens": 2048,
            },
        )

    def on_init(self, agent: Any) -> None:
        """初始化辩论 Agent 群和独立的裁判 Agent（仅调用一次）。"""
        logger.info("[Defense] Debate: Initializing 3 debaters and 1 judge agent.")
        from camel.agents.chat_agent import ChatAgent
        from camel.messages import BaseMessage

        # 1. 创建辩论者
        debate_agents = []
        for i in range(self.NUM_DEBATERS):
            sys_msg = BaseMessage.make_assistant_message(
                role_name=f"{agent.assistant_role} (Debater {i+1})",
                content=agent._make_system_prompt(agent.system_assistant),
            )
            # 使用对应索引的模型
            current_model = self.debate_models[i % len(self.debate_models)]
            debate_agents.append(ChatAgent(
                sys_msg, 
                model=current_model,
                token_limit=agent.token_limit,
                message_window_size=agent.message_window_size,
                summarize_threshold=70  # 禁用中间摘要，保证辩论上下文完整
            ))
        
        # 2. 创建独立的裁判，强制要求仅输出选出的编号
        judge_sys_msg = BaseMessage.make_assistant_message(
            role_name="Vote Judge",
            content="You are a strict output controller. Your only job is to select the index of the best candidate answer (e.g., '1', '2', or '3') and output ONLY that number. Never include reasoning or the answer content itself."
        )
        judge_agent = ChatAgent(
            judge_sys_msg, 
            model=self.judge_model,
            token_limit=agent.token_limit,
            message_window_size=agent.message_window_size,
            summarize_threshold=70  # 裁判也需要完整视图
        )

        self._debate_agents_map[id(agent)] = debate_agents
        self._judge_agents_map[id(agent)] = judge_agent

    def on_reset(self, agent: Any, goal: str = "", context: str = "") -> str | None:
        """reset 阶段重置辩论 Agent 对话历史（不重建）。"""
        debate_agents = self._debate_agents_map.get(id(agent))
        if debate_agents:
            for da in debate_agents:
                da.reset()
        judge_agent = self._judge_agents_map.get(id(agent))
        if judge_agent:
            judge_agent.reset()
        return None

    def on_step(self, agent: Any, func: Callable, message_from_peer: str, context: dict) -> str | None:
        """
        仅拦截 assistant_step。
        判断依据：func.__name__ == "assistant_step"
        """
        if func.__name__ != "assistant_step":
            return None  # user_step 不拦截

        debate_agents = self._debate_agents_map.get(id(agent))
        if not debate_agents:
            return None

        logger.info("-" * 30 + " DEBATE START " + "-" * 30)
        logger.info("[Defense] Debate: Intercepting assistant_step with %d debaters.", len(debate_agents))

        # ── 第一步：独立答题 ──
        context_docs = context.get("context", "")
        logger.info("[Debate] Phase 1: Independent Answering (Context length: %d)", len(context_docs))
        answers = []
        for i, da in enumerate(debate_agents):
            prompt = self.initial_prompt.format(
                task_input=message_from_peer, 
                context=context_docs
            )
            response = da.step(prompt)
            ans = response.msg.content if response.msg else ""
            answers.append(ans)
            logger.info("[Debate] Debater %d initial answer: %s...", i + 1, ans.replace("\n", " "))

        # ── 第二步：多轮互相修正 ──
        for round_idx in range(self.DEBATE_ROUNDS):
            logger.info("[Debate] Phase 2: Refinement Round %d", round_idx + 1)
            new_answers = []
            for i, da in enumerate(debate_agents):
                others = [answers[j] for j in range(len(answers)) if j != i]
                others_text = "\n---\n".join(
                    f"Agent {j+1}: {a}" for j, a in enumerate(others)
                )
                debate_input = self.debate_prompt.format(
                    task_input=message_from_peer,
                    my_answer=answers[i],
                    other_answers=others_text,
                )
                response = da.step(debate_input)
                refined = response.msg.content if response.msg else answers[i]
                new_answers.append(refined)
                logger.info("[Debate] Debater %d refined answer: %s...", i + 1, refined.replace("\n", " "))
            answers = new_answers

        # ── 第三步：投票 / 共识 ──
        logger.info("[Debate] Phase 3: Voting for consensus")
        consensus = self._vote(agent, answers, message_from_peer)
        logger.info("-" * 30 + " DEBATE END " + "-" * 30)
        return consensus

    def _vote(self, agent: Any, answers: list[str], original_input: str) -> str:
        """使用独立的 judge_agent 选出最佳答案的编号，并返回对应的原始答案内容。"""
        judge_agent = self._judge_agents_map.get(id(agent))
        if not judge_agent:
            judge_agent = agent.assistant_agent

        candidates_text = "\n---\n".join(
            f"Candidate {i+1}: {a}" for i, a in enumerate(answers)
        )
        vote_input = self.vote_prompt.format(
            task_input=original_input,
            candidates=candidates_text,
        )
        
        response = judge_agent.step(vote_input)
        logger.info("[Debate] Judge response: %s", response.msg.content)
        vote_output = response.msg.content.strip() if response.msg else "1"
        logger.info("[Debate] Judge selected candidate number: %s", vote_output)

        # 尝试提取数字
        import re
        match = re.search(r'\d+', vote_output)
        if match:
            idx = int(match.group()) - 1
            if 0 <= idx < len(answers):
                logger.info("[Debate] Returning answer from Candidate %d", idx + 1)
                logger.info("[Debate] Returning answer: %s", answers[idx])
                return answers[idx]
        
        logger.warning("[Debate] Judge failed to provide valid index. Falling back to Candidate 1.")
        return answers[0]


    def on_message(self, peer_msg: str, context: dict) -> str:
        return peer_msg


# ── 注册表与工厂 ────────────────────────────────────────────────────

DEFENSE_REGISTRY: dict[str, type[BaseDefense]] = {
    "challenger": ChallengerDefense,
    "inspector": InspectorDefense,
    "input": InputDefense,
    "debate": DebateVotingDefense,
}


_defense_instances: dict[str, BaseDefense] = {}


def get_defense(defense_type: str) -> BaseDefense | None:
    """
    根据 defense_type 返回对应的 Defense 实例。
    使用单例模式缓存实例，确保 on_reset 和 on_step 共享状态。

    Args:
        defense_type: 防御类型名称（如 "challenger", "inspector", "debate", "none"）
    """
    if defense_type == "none" or not defense_type:
        return None

    if defense_type not in _defense_instances:
        cls = DEFENSE_REGISTRY.get(defense_type)
        if cls is None:
            logger.warning("[Defense] Unknown defense type: %s. No defense applied.", defense_type)
            return None
        _defense_instances[defense_type] = cls()

    return _defense_instances[defense_type]

