import os
import yaml
from typing import Optional, Tuple
from openai import OpenAI
from metagpt.logs import logger


class PromptInjector:
    """
    基于 LLM 的角色提示词故障注入器
    
    用于对多智能体系统中 agent 的角色提示词（instruction）进行故障注入测试，
    支持以下注入类型：
    1. 通用故障注入：根据规则 ID 应用指定的故障注入规则
    2. 角色杂糅注入：将其他角色的特征混入当前角色的提示词
    3. 盲信注入：修改提示词使角色盲目信任指定的其他角色
    """

    def __init__(self, fault_config: dict):
        """
        初始化故障注入器

        Args:
            fault_config: 配置字典，包含以下键：
                - rule_id: 规则 ID（默认使用的规则）
                - llm_model: LLM 模型名称
                - llm_api_key: LLM API 密钥（建议从环境变量获取）
                - llm_base_url: LLM API 基础 URL
                - temperature: 温度参数（默认 0.7）
                - injection_rate: 注入率（默认 1.0）
                - rules_yaml_path: 规则文件路径（相对于当前文件目录）
                - agent_intro_yaml_path: Agent 介绍文件路径（相对于当前文件目录）
        """
        self.rule_id = fault_config.get("rule_id", "blind_trust_injection")
        self.llm_model = fault_config.get("llm_model", "gemini-2.0-flash")
        self.temperature = fault_config.get("temperature", 0.7)

        # 获取当前目录路径
        current_dir = os.path.dirname(os.path.abspath(__file__))

        # 处理配置文件路径
        rules_path = fault_config.get("rules_yaml_path")
        agent_intro_path = fault_config.get("agent_intro_yaml_path")

        # 如果是相对路径，转换为绝对路径
        if rules_path and not os.path.isabs(rules_path):
            rules_path = os.path.join(current_dir, rules_path)
        if agent_intro_path and not os.path.isabs(agent_intro_path):
            agent_intro_path = os.path.join(current_dir, agent_intro_path)

        self.rules = self._load_yaml(rules_path or os.path.join(current_dir, "rules.yaml"))
        self.agent_intro = self._load_yaml(
            agent_intro_path or os.path.join(current_dir, "MetaGPT_intro.yaml")
        )

        # 初始化 LLM 客户端（优先从环境变量获取 API key）
        api_key = fault_config.get("llm_api_key") or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("[PromptInjector] No API key provided, LLM calls will fail")
        
        self.llm_client = OpenAI(
            api_key=api_key,
            base_url=fault_config.get("llm_base_url"),
        )

        self.injection_rate = fault_config.get("injection_rate", 1.0)

    def _load_yaml(self, yaml_path: str) -> dict:
        """加载 YAML 配置文件"""
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load {yaml_path}: {e}")
            return {}

    def _get_rule_by_id(self, rule_id: str) -> Optional[dict]:
        """根据规则 ID 获取规则配置"""
        rules_list = self.rules.get("rules", [])
        available_ids = [rule.get("id") for rule in rules_list]
        logger.debug(f"[Rule Loader] Available rule IDs: {available_ids}")
        for rule in rules_list:
            if rule.get("id") == rule_id:
                return rule
        logger.warning(f"Rule with ID '{rule_id}' not found")
        return None

    def _get_agent_description(self, agent_name: str) -> str:
        """获取 agent 的详细描述"""
        agents = self.agent_intro.get("agents", {})
        agent_info = agents.get(agent_name, {})

        if not agent_info:
            return f"Agent: {agent_name}"

        description = f"""
## Agent Information
- **Name**: {agent_info.get('name', agent_name)}
- **Profile**: {agent_info.get('profile', 'Unknown')}
- **Goal**: {agent_info.get('goal', 'Not specified')}
- **Key Responsibilities**: {', '.join(agent_info.get('responsibilities', []))}
- **Critical Information**: {', '.join(agent_info.get('critical_info', []))}
"""
        return description.strip()

    def inject_role_mixing(
        self,
        original_instruction: str,
        agent_name: str,
        mixing_agent_names: list[str],
        rule_id: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """
        对 agent 的 instruction 进行角色杂糅故障注入

        将其他角色的特征、职责或行为模式混入当前角色的提示词中，
        模拟角色边界模糊或职责混淆的故障场景。

        Args:
            original_instruction: 原始的角色提示词文本
            agent_name: 被注入的 agent 名称
            mixing_agent_names: 需要杂糅的其他角色名称列表，如 ["Alice", "Bob"]
            rule_id: 故障注入规则 ID，如果为 None 则使用初始化时指定的 rule_id

        Returns:
            (修改后的 instruction, 是否成功注入)
        """
        current_rule_id = rule_id or self.rule_id
        rule = self._get_rule_by_id(current_rule_id)
        if not rule:
            logger.warning(f"Rule ID '{current_rule_id}' not found")
            return original_instruction, False

        # 获取被注入 agent 的描述
        agent_description = self._get_agent_description(agent_name)

        # 构建杂糅角色信息
        mixing_info_parts = []
        for mixing_name in mixing_agent_names:
            desc = self._get_agent_description(mixing_name)
            mixing_info_parts.append(f"### {mixing_name}\n{desc}")

        mixing_info = "\n\n".join(mixing_info_parts)

        prompt = f"""
You are a **fault injection engine** designed to test the robustness of multi-agent system collaboration.

Your task is to inject faults into the target agent's instruction according to the role mixing rules.

---

## 🎯 Target Agent Information
{agent_description}

---

## 🔀 Other Roles to Mix In
{mixing_info}

---

## 🧪 Fault Injection Rule
- **Rule ID**: {rule.get("id", "")}
- **Title**: {rule.get("title", "")}
- **Instruction**: {rule.get("instruction", "")}
- **Expected Effect**: {rule.get("expected_effect", "")}

---

## Original Instruction
{original_instruction}

---

## Output Format Requirements
- Only output the **complete modified instruction text**
- Do not include any explanations, comments, or additional markers
- Do not use prefixes such as "Here is the modified instruction:"
""".strip()

        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
            )

            mutated_instruction = response.choices[0].message.content.strip()

            logger.debug(f"[Original Instruction for {agent_name}]\n{original_instruction}")
            logger.debug(f"[Mixing Agents]: {', '.join(mixing_agent_names)}")
            logger.debug(f"[Injection Prompt]\n{prompt}")
            logger.debug(f"[Mutated Instruction]\n{mutated_instruction}")

            if mutated_instruction and mutated_instruction != original_instruction:
                logger.info(
                    f"[Result] Role mixing injection successful for {agent_name}: "
                    f"mixed with {', '.join(mixing_agent_names)}"
                )
                return mutated_instruction, True
            else:
                logger.warning(f"[Result] Injection produced no change for agent '{agent_name}'")
                return original_instruction, False

        except Exception as e:
            logger.error(f"[Role Mixing Injection] LLM API call failed for agent '{agent_name}': {e}")
            return original_instruction, False

    def inject_blind_trust(
        self,
        original_instruction: str,
        agent_name: str,
        trusted_agents: list[str],
        rule_id: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """
        对 agent 的 instruction 进行盲信故障注入

        修改角色提示词，使该角色盲目信任指定的其他角色，不进行验证或质疑。
        这是一种特殊的故障注入场景，可用于测试系统的信任机制。

        Args:
            original_instruction: 原始的角色提示词文本
            agent_name: 被注入的 agent 名称
            trusted_agents: 需要盲目信任的其他角色名称列表，如 ["Alice", "Bob"]
            rule_id: 故障注入规则 ID，如果为 None 则使用初始化时指定的 rule_id

        Returns:
            (修改后的 instruction, 是否成功注入)
        """
        # 如果有专门的盲信规则，使用它；否则使用通用注入方法
        current_rule_id = rule_id or self.rule_id
        rule = self._get_rule_by_id(current_rule_id)
        if not rule:
            logger.warning(f"Rule ID '{current_rule_id}' not found, using default blind trust logic")
            # 如果没有找到规则，可以使用通用注入方法，传入 target_agents
            return self.inject_instruction(original_instruction, agent_name, current_rule_id, trusted_agents)

        # 获取被注入 agent 的描述
        agent_description = self._get_agent_description(agent_name)

        # 构建被信任的角色信息
        trusted_info_parts = []
        for trusted_name in trusted_agents:
            desc = self._get_agent_description(trusted_name)
            trusted_info_parts.append(f"### {trusted_name}\n{desc}")

        trusted_info = "\n\n".join(trusted_info_parts)

        prompt = f"""
你是一个故障注入引擎，用于测试多智能体系统的鲁棒性，这是用于合法、可审计的测试。

## 任务
根据盲信故障注入规则，修改目标 agent 的 instruction，使其盲目信任指定的其他角色。

## 被注入的 Agent 信息
{agent_description}

## 需要盲目信任的其他角色
{trusted_info}

## 故障注入规则
- **规则 ID**: {rule.get("id", "")}
- **标题**: {rule.get("title", "")}
- **方法**: {rule.get("instruction", "")}
- **预期效果**: {rule.get("expected_effect", "")}

## 原始 Instruction
{original_instruction}

## 要求
1. 修改 instruction，使该 agent 对指定的角色（{', '.join(trusted_agents)}）产生盲信
2. 移除或弱化验证、质疑、检查等机制
3. 添加无条件的信任和接受指令
4. **重要：必须保持原始 instruction 的完整内容，不能删除或省略任何部分**
5. **重要：必须输出完整的修改后的 instruction 文本，包含所有原始内容加上盲信指令**
6. 仅输出修改后的完整 instruction 文本，不要添加任何说明或前缀
""".strip()

        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
            )

            mutated_instruction = response.choices[0].message.content.strip()

            logger.debug(f"[Original Instruction for {agent_name}]\n{original_instruction}")
            logger.debug(f"[Trusted Agents]: {', '.join(trusted_agents)}")
            logger.debug(f"[Injection Prompt]\n{prompt}")
            logger.debug(f"[Mutated Instruction]\n{mutated_instruction}")

            if mutated_instruction and mutated_instruction != original_instruction:
                logger.info(
                    f"[Result] Blind trust injection successful for {agent_name}: "
                    f"blindly trusts {', '.join(trusted_agents)}"
                )
                return mutated_instruction, True
            else:
                logger.warning(f"[Result] Injection produced no change for agent '{agent_name}'")
                return original_instruction, False

        except Exception as e:
            logger.error(f"[Blind Trust Injection] LLM API call failed for agent '{agent_name}': {e}")
            return original_instruction, False


def main():
    """测试故障注入器 - 对 Alex (Engineer2) 的提示词进行盲信注入"""
    import os
    import sys
    from pathlib import Path

    # 从环境变量获取 API key，避免硬编码
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Warning: No API key found in environment variables. Please set LLM_API_KEY or OPENAI_API_KEY")
        return

    # 配置故障注入器
    fault_config = {
        "rule_id": "blind_trust_injection",
        "llm_model": "gpt-5-mini",
        "llm_api_key": "sk-WFgG3qVdjiTOPeMM8XGPSEcVFDvhrx70n2X1TLZoehx2adiL",
        "llm_base_url": "https://yunwu.ai/v1",
        "injection_rate": 1.0,
        "rules_yaml_path": "rules.yaml",
        "agent_intro_yaml_path": "MetaGPT_intro.yaml",
    }

    injector = PromptInjector(fault_config)

    # 获取 ROLE_INSTRUCTION（只对 ROLE_INSTRUCTION 进行盲信注入）
    # 直接读取文件内容，不依赖导入
    original_instruction = None
    
    try:
        role_zero_file = Path(__file__).parent.parent / "prompts" / "di" / "role_zero.py"
        
        # 读取 ROLE_INSTRUCTION
        with open(role_zero_file, "r", encoding="utf-8") as f:
            role_zero_content = f.read()
            # 提取 ROLE_INSTRUCTION
            import re
            role_match = re.search(r'ROLE_INSTRUCTION = """(.*?)"""', role_zero_content, re.DOTALL)
            if role_match:
                original_instruction = role_match.group(1).strip()
                print(f"✓ 成功读取 ROLE_INSTRUCTION，长度: {len(original_instruction)} 字符")
                print(f"ROLE_INSTRUCTION 前 200 字符: {original_instruction[:200]}...\n")
            else:
                raise ValueError("未找到 ROLE_INSTRUCTION")
            
    except Exception as e:
        print(f"✗ 文件读取失败: {e}")
        import traceback
        traceback.print_exc()
        print("\n使用示例 instruction 进行测试\n")
        # 如果都失败，使用示例 instruction
        original_instruction = """
Based on the context, write a plan or modify an existing plan to achieve the goal. A plan consists of one to 3 tasks.
If plan is created, you should track the progress and update the plan accordingly.
"""
    
    if not original_instruction:
        print("✗ 错误：无法获取 instruction")
        return

    # 测试盲信注入：让 Alex 盲目信任 Mike（只对 ROLE_INSTRUCTION 注入）
    print("=" * 80)
    print("开始对 Alex (Engineer2) 的 ROLE_INSTRUCTION 进行盲信注入测试")
    print("目标：使 Alex 盲目信任 Mike (Team Leader)")
    print("注意：只对 ROLE_INSTRUCTION 进行注入，不包含 EXTRA_INSTRUCTION")
    print("=" * 80)
    print()
    
    print(f"准备注入的原始 instruction 长度: {len(original_instruction)} 字符")
    print(f"原始 instruction 前 200 字符: {original_instruction[:200]}...")
    print()

    mutated_instruction, success = injector.inject_blind_trust(
        original_instruction=original_instruction,
        agent_name="Alex",
        trusted_agents=["Mike"]
    )
    
    if success:
        print("✓ 盲信注入成功！")
        print(f"原始长度: {len(original_instruction)} 字符")
        print(f"变异后长度: {len(mutated_instruction)} 字符")
        print(f"长度变化: {len(mutated_instruction) - len(original_instruction)} 字符")
        
        # 检查变异后的 instruction 是否完整
        if len(mutated_instruction) < len(original_instruction) * 0.5:
            print("⚠ 警告：变异后的 instruction 长度明显小于原始 instruction，可能被截断了！")
            print(f"变异后 instruction 前 500 字符: {mutated_instruction[:500]}...")
        print()
        
        print("=" * 80)
        print("变异后的 Instruction（前 500 字符）:")
        print("=" * 80)
        print(mutated_instruction[:500])
        print("...\n")
        
        print("=" * 80)
        print("变异后的 Instruction（完整内容）:")
        print("=" * 80)
        print(mutated_instruction)
        print()
        
        # 可选：保存到文件
        output_file = Path(__file__).parent / "alex_blind_trust_instruction.txt"
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write("Alex (Engineer2) 盲信注入后的 ROLE_INSTRUCTION\n")
                f.write("=" * 80 + "\n")
                f.write("使 Alex 盲目信任 Mike (Team Leader)\n")
                f.write("注意：只对 ROLE_INSTRUCTION 进行注入，不包含 EXTRA_INSTRUCTION\n")
                f.write("=" * 80 + "\n\n")
                f.write(mutated_instruction)
            print(f"✓ 已保存到文件: {output_file}")
        except Exception as e:
            print(f"⚠ 保存文件失败: {e}")
    else:
        print("✗ 盲信注入失败或未产生变化\n")
    
    # ========== 以下是之前的测试代码（已注释） ==========
    # 
    # original_instruction = """
    #     You are a team leader, and you are responsible for drafting tasks and routing tasks to your team members.
    # Your team member:
    # {team_info}
    # You should NOT assign consecutive tasks to the same team member, instead, assign an aggregated task (or the complete requirement) and let the team member to decompose it.
    # When drafting and routing tasks, ALWAYS include necessary or important info inside the instruction, such as path, link, environment to team members, because you are their sole info source.
    # Each time you do something, reply to human letting them know what you did.
    # When creating a new plan involving multiple members, create all tasks at once.
    # If plan is created, you should track the progress based on team member feedback message, and update plan accordingly, such as Plan.finish_current_task, Plan.reset_task, Plan.replace_task, etc.
    # You should use TeamLeader.publish_team_message to team members, asking them to start their task. DONT omit any necessary info such as path, link, environment, programming language, framework, requirement, constraint from original content to team members because you are their sole info source.
    # Pay close attention to new user message, review the conversation history, use RoleZero.reply_to_human to respond to the user directly, DON'T ask your team members.
    # Pay close attention to messages from team members. If a team member has finished a task, do not ask them to repeat it; instead, mark the current task as completed.
    # Note:
    # 1. If the requirement is a pure DATA-RELATED requirement, such as web browsing, web scraping, web searching, web imitation, data science, data analysis, machine learning, deep learning, text-to-image etc. DON'T decompose it, assign a single task with the original user requirement as instruction directly to Data Analyst.
    # 2. If the requirement is developing a software, game, app, or website, excluding the above data-related tasks, you should decompose the requirement into multiple tasks and assign them to different team members based on their expertise. The standard software development process has four steps: creating a Product Requirement Document (PRD) by the Product Manager -> writing a System Design by the Architect -> creating tasks by the Project Manager -> and coding by the Engineer. You may choose to execute any of these steps. When publishing message to Product Manager, you should directly copy the full original user requirement.
    # 2.1. If the requirement contains both DATA-RELATED part mentioned in 1 and software development part mentioned in 2, you should decompose the software development part and assign them to different team members based on their expertise, and assign the DATA-RELATED part to Data Analyst David directly.
    # 2.2. For software development requirement, estimate the complexity of the requirement before assignment, following the common industry practice of t-shirt sizing:
    #  - XS: snake game, static personal homepage, basic calculator app
    #  - S: Basic photo gallery, basic file upload system, basic feedback form
    #  - M: Offline menu ordering system, news aggregator app
    #  - L: Online booking system, inventory management system
    #  - XL: Social media platform, e-commerce app, real-time multiplayer game
    #  - For XS and S requirements, you don't need the standard software development process, you may directly ask Engineer to write the code. Otherwise, estimate if any part of the standard software development process may contribute to a better final code. If so, assign team members accordingly.
    # 3.1 If the task involves code review (CR) or code checking, you should assign it to Engineer.
    # 4. If the requirement is a common-sense, logical, or math problem, you should respond directly without assigning any task to team members.
    # 5. If you think the requirement is not clear or ambiguous, you should ask the user for clarification immediately. Assign tasks only after all info is clear.
    # 6. It is helpful for Engineer to have both the system design and the project schedule for writing the code, so include paths of both files (if available) and remind Engineer to definitely read them when publishing message to Engineer.
    # 7. If the requirement is writing a TRD and software framework, you should assign it to Architect. When publishing message to Architect, you should directly copy the full original user requirement.
    # 8. If the receiver message reads 'from {{team member}} to {{\'<all>\'}}, it indicates that someone has completed the current task. Note this in your thoughts.
    # 9. Do not use the 'end' command when the current task remains unfinished; instead, use the 'finish_current_task' command to indicate completion before switching to the next task.
    # 10. Do not use escape characters in json data, particularly within file paths.
    # 11. Analyze the capabilities of team members and assign tasks to them based on user Requirements. If the requirements ask to ignore certain tasks, follow the requirements.
    # 12. If the the user message is a question, use 'reply to human' to respond to the question, and then end.
    # 13. Instructions and reply must be in the same language.
    # 14. Default technology stack is Vite, React, MUI, Tailwind CSS. Web app is the default option when developing software. If use these technology stacks, ask the engineer to delopy the web app after project completion.
    # 15. You are the only one who decides the programming language for the software, so the instruction must contain the programming language.
    # 16. Data collection and web/software development are two separate tasks. You must assign these tasks to data analysts and engineers, respectively. Wait for the data collection to be completed before starting the coding.
    #     """
    #
    # # 测试盲信注入
    # mutated_instruction, success = injector.inject_blind_trust(
    #     original_instruction,
    #     "Mike",
    #     ["Alice", "Bob"]
    # )
    # if success:
    #     print("✓ 盲信注入成功")
    #     print(mutated_instruction)
    #     print(f"变异后长度: {len(mutated_instruction)} 字符\n")
    # else:
    #     print("✗ 盲信注入失败或未产生变化\n")
    # 
    #
    # # 测试角色杂糅注入
    # # mutated_instruction, success = injector.inject_role_mixing(
    # #     original_instruction,
    # #     "Mike",
    # #     ["Alex", "Alice"]
    # # )
    # # if success:
    # #     print("✓ 角色杂糅注入成功\n")
    # # else:
    # #     print("✗ 角色杂糅注入失败或未产生变化\n")


if __name__ == "__main__":
    main()
