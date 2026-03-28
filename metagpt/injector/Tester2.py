import functools
import random
import yaml
import json
# import logging
import os
from pathlib import Path
from typing import Callable, Optional, Set, Tuple, Dict, Any
from functools import wraps
from metagpt.schema import Message
import os
# 设置日志存储路径
# log_dir = os.path.expanduser("/Users/ximenajia/CODE/Tester/logs")  # 你可以改成任意你有权限的目录
# os.makedirs(log_dir, exist_ok=True)  # 自动创建目录（如果不存在）
# log_path = os.path.join(log_dir, "tester_storm.log")

# logging.basicConfig(
#     filename=log_path,
#     level=logging.INFO,
#     format="%(asctime)s - %(levelname)s - %(message)s"
# )
# logger = logging.getLogger(__name__)
# logger.info("日志系统初始化完成")
from metagpt.logs import logger
from typing import Set, Dict, Any
import yaml

class InjectorConfig:
    """消息损坏配置"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            # 使用相对于当前文件的路径
            current_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(current_dir, "injector_config.yaml")
            
        logger.info(f"Loading config from: {config_path}")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)  # 直接加载数据，不需要.get("message_corruption")
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {config_path}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML file: {e}")
            raise

        # 顶层配置项
        self.enabled: bool = data.get("enabled", False)
        self.target_senders: Set[str] = set(data.get("target_senders", []))
        
        # 嵌套的 LLM 注入配置
        llm_data = data.get("llm_injection", {})
        self.llm_injection: Dict[str, Any] = {
            "enabled": llm_data.get("enabled", False),
            "llm_model": llm_data.get("llm_model", "gpt-4"),  # 修改键名以匹配配置
            "temperature": llm_data.get("temperature", 0.7),
            "llm_api_key": llm_data.get("llm_api_key", ""),
            "llm_base_url": llm_data.get("llm_base_url", ""),
            "rules_yaml_path": llm_data.get("rules_yaml_path", "rules.yaml"),
            "agent_intro_yaml_path": llm_data.get("agent_intro_yaml_path", "agent_intro.yaml"),
            "rule_id": llm_data.get("rule_id", "info_loss_critical"),
            "tools_intro_yaml_path": llm_data.get("tools_intro_yaml_path", "MetaGPT_tools_intro.yaml"),
            "target_receiver": llm_data.get("target_receiver"),  # 目标接收者（单个字符串，可选）
        }

        # 工具调用故障配置injection_rate
        tool_data = data.get("tool_calling_faults", {})
        self.tool_calling_faults: Dict[str, Any] = {
            "enabled": tool_data.get("enabled", False),
            "injection_rate": tool_data.get("injection_rate", 0.0),  # 默认0%注入率
            "rule_id": tool_data.get("rule_id", "tool_command_error"),
            "llm_base_url": tool_data.get("llm_base_url", ""),
            "rules_yaml_path": tool_data.get("rules_yaml_path", "rules.yaml"),
            "tools_intro_yaml_path": tool_data.get("tools_intro_yaml_path", "MetaGPT_tools_intro.yaml"),
            "llm_api_key": tool_data.get("llm_api_key", ""),
            "llm_model": tool_data.get("llm_model", "gemini-2.0-flash"),
            "temperature": tool_data.get("temperature", 0.7)
        }
        
        # 嵌套的通信故障配置
        comm_data = data.get("communication_faults", {})
        self.communication_faults: Dict[str, Any] = {
            "enabled": comm_data.get("enabled", False),
            "rule_id": comm_data.get("rule_id", "")
        }
        # 嵌套的输入提示词故障配置
        input_data = data.get("input_prompt_faults", {})
        self.input_prompt_faults: Dict[str, Any] = {
            "enabled": input_data.get("enabled", False),
            "llm_model": input_data.get("llm_model", "gpt-4"),
            "temperature": input_data.get("temperature", 0.7),
            "llm_api_key": input_data.get("llm_api_key", ""),
            "llm_base_url": input_data.get("llm_base_url", ""),
            "rules_yaml_path": input_data.get("rules_yaml_path", "rules.yaml"),
            "agent_intro_yaml_path": input_data.get("agent_intro_yaml_path", "agent_intro.yaml"),
            "rule_id": input_data.get("rule_id", "goal_unclear"),
        }
class FaultInjector:  
    """基于 LLM 的故障注入器"""  
      
    def __init__(self, fault_config: dict):  
        """初始化故障注入器"""  
        """初始化故障注入器"""  
        self.rule_id = fault_config.get("rule_id")  
        self.llm_model = fault_config.get("llm_model", "gemini-2.0-flash")  
        self.temperature = fault_config.get("temperature", 0.7)  
          
        # 获取当前目录路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 使用绝对路径加载配置文件
        rules_path = fault_config.get("rules_yaml_path")
        tools_intro_path = fault_config.get("tools_intro_yaml_path")
        agent_intro_path = fault_config.get("agent_intro_yaml_path")
        
        # 如果是相对路径，转换为绝对路径
        if rules_path and not os.path.isabs(rules_path):
            rules_path = os.path.join(current_dir, rules_path)
        if tools_intro_path and not os.path.isabs(tools_intro_path):
            tools_intro_path = os.path.join(current_dir, tools_intro_path)
        if agent_intro_path and not os.path.isabs(agent_intro_path):
            agent_intro_path = os.path.join(current_dir, agent_intro_path)
            
        self.rules = self._load_yaml(rules_path or os.path.join(current_dir, "tool_fault_rules.yaml"))
        self.agent_intro = self._load_yaml(agent_intro_path or os.path.join(current_dir, "MetaGPT_intro.yaml"))
        self.tools_intro = self._load_yaml(tools_intro_path or os.path.join(current_dir, "MetaGPT_tools_intro.yaml"))
        self.rule_id = fault_config.get("rule_id", "info_loss_critical") 
        
        
        # 初始化 Gemini API
        # genai.configure(api_key=fault_config.get("llm_api_key"))
        # self.model = genai.GenerativeModel(self.llm_model)
        # 初始化 LLM 客户端 
        from openai import OpenAI
        self.llm_client = OpenAI(  
            api_key=fault_config.get("llm_api_key"),  
            base_url=fault_config.get("llm_base_url"),  
        )
        # print("apikey:", fault_config.get("llm_api_key"))
        # print("base_url:", fault_config.get("llm_base_url"))
        # print("llm_model:", self.llm_model)
        # print("temperature:", self.temperature)
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
        logger.info(f"[Rule Loader] Available rule IDs: {available_ids}") 
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
- **Critical Information Types**: {', '.join(agent_info.get('critical_info', []))}  
"""  
        return description.strip()  
      
    # 这是针对agent系统中agent的上下文做的故障注入
    def inject(  
    self,   
    context: str,   
    agent_name: str,  
    goal: str,
    receiver_name: Optional[str] = None,  # 接收者名称，用于记忆丢失等场景
) -> Tuple[str, bool]:  
        """  
        执行故障注入，并记录完整日志
        
        Args:
            context: 原始消息内容
            agent_name: 发送者agent名称
            goal: 当前任务目标
            receiver_name: 接收者agent名称（可选），用于根据接收者调整注入策略
        """  
        rule = self._get_rule_by_id(self.rule_id)  
        if not rule:  
            logger.warning(f"Rule ID '{self.rule_id}' not found")  
            return context, False
        
        # 如果是事实链条注入，使用专门的注入方法（不需要LLM）
        if self.rule_id == "long_context_injection":
            logger.info(f"[long_context_inject] Using fact chain injection method (no LLM required)")
            logger.info(f"[long_context_inject] Original context length: {len(context)}")
            logger.info(f"[long_context_inject] Agent: {agent_name}, Receiver: {receiver_name}")
            result, success = self.long_context_inject(context, agent_name, goal, receiver_name)
            logger.info(f"[long_context_inject] Injection result - Success: {success}, Result length: {len(result) if result else 0}")
            return result, success

        # Inline prompt construction (inlined from former _build_injection_prompt)
        system_intro = self.agent_intro.get("system_description", "")
        agent_description = self._get_agent_description(agent_name)
        
        # 如果有接收者信息，获取接收者描述
        receiver_description = ""
        if receiver_name:
            receiver_description = self._get_agent_description(receiver_name)
        
        # 构建接收者部分（避免在f-string表达式中使用反斜杠）
        receiver_section = f"## Receiver Role Description  \n{receiver_description}  \n---\n" if receiver_name else ""
        
        prompt = f"""
You are a fault injection engine designed to test the robustness of multi-agent systems.  
Your task is to semantically mutate messages according to predefined rules, while maintaining contextual coherence and natural language fluency.  

---
## Sender Role Description  
{agent_description}  
{receiver_section}
## Introduction to the Agent System  
{system_intro}  

---

## Current Task Goal  
{goal if goal else "No specific goal provided"}  

---

## Mutation Rule  
- **Rule ID**: {rule.get("id", "")}  
- **Title**: {rule.get("title", "")}  
- **Instruction**: {rule.get("instruction", "")}  

---

## Original Message from {agent_name}  
{context}  

---

## Task Requirements  
1. Apply the mutation rule considering the sender's role{f" and the receiver's role ({receiver_name})" if receiver_name else ""} and the current task goal.  
2. Prioritize introducing semantic faults that affect the transmission of key information.  
3. Preserve the basic structure and natural fluency of the message.  
4. Consider the agent's communication style and common information exchange patterns.  
{f"5. If the rule involves memory loss or information filtering, adjust the mutation based on what information the receiver ({receiver_name}) should lose according to the rule." if receiver_name else ""}

---

## Output Format Requirements  
- Only output the mutated message text (plain text).  
- Do not include any explanations, comments, or additional markers.  
- Do not use prefixes such as "Here is the mutated message:".  

""".strip()
        try:
            print("🥹😭注入提示词：", prompt)
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
            )
            print("😭注入响应：", response)
            mutated = response.choices[0].message.content.strip()

            # 记录完整日志内容  
            logger.info(f"[Original Message]\n{context}")  
            logger.info(f"[Injection Prompt]\n{prompt}")  
            logger.info(f"[Mutated Message]\n{mutated}")  

            if mutated and mutated != context:  
                logger.info(f"[Result] Mutation successful: {len(context)} → {len(mutated)} chars")  
                return mutated, True  
            else:  
                logger.warning(f"[Result] Mutation produced no change for agent '{agent_name}'")  
                return context, False  

        except Exception as e:  
            logger.error(f"[Fault Injection] Gemini API call failed for agent '{agent_name}': {e}")  
            return context, False
    
    def long_context_inject(
        self,
        context: str,
        agent_name: str,
        goal: str,
        receiver_name: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """
        事实链条（Fact Chain）注入：将有用信息拆解为多个逻辑不连续的片段，穿插到长文本中
        
        Args:
            context: 原始消息内容
            agent_name: 发送者agent名称
            goal: 当前任务目标
            receiver_name: 接收者agent名称（可选）
        
        Returns:
            (修改后的消息, 是否成功注入)
        """
        import re
        from pathlib import Path
        
        # PG-19 文本文件路径 - 使用相对于当前文件的路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        pg19_text_path = Path(current_dir) / "10146.txt"
        
        logger.info(f"[long_context_inject] Looking for PG-19 text file at: {pg19_text_path}")
        logger.info(f"[long_context_inject] File exists: {pg19_text_path.exists()}")
        
        if not pg19_text_path.exists():
            logger.error(f"[long_context_inject] PG-19 text file not found: {pg19_text_path}")
            logger.error(f"[long_context_inject] Current directory: {current_dir}")
            logger.error(f"[long_context_inject] Working directory: {os.getcwd()}")
            return context, False
        
        try:
            # 读取 PG-19 文本
            with open(pg19_text_path, "r", encoding="utf-8") as f:
                pg19_text = f.read()
            
            logger.info(f"[long_context_inject] Loaded PG-19 text: {len(pg19_text)} characters")
            
            # 将原始消息拆解为事实片段
            # 按句子拆分（支持中英文句号、问号、感叹号）
            sentences = re.split(r'[。！？.!?]\s*', context)
            sentences = [s.strip() for s in sentences if s.strip()]
            
            # 如果句子太少，尝试按段落拆分
            if len(sentences) < 3:
                paragraphs = re.split(r'\n\s*\n', context)
                paragraphs = [p.strip() for p in paragraphs if p.strip()]
                if len(paragraphs) >= 3:
                    sentences = paragraphs[:5]  # 最多取5个段落
                else:
                    # 如果还是太少，按逗号拆分
                    sentences = re.split(r'[，,]\s*', context)
                    sentences = [s.strip() for s in sentences if s.strip()][:5]
            
            # 确保至少有3个片段，最多5个
            fact_fragments = sentences[:5] if len(sentences) >= 3 else sentences
            
            if len(fact_fragments) < 3:
                logger.warning(f"[long_context_inject] Not enough fragments ({len(fact_fragments)}), using original message")
                return context, False
            
            logger.info(f"[long_context_inject] Decomposed into {len(fact_fragments)} fact fragments")
            
            # 计算插入位置（10%, 50%, 90%）
            text_length = len(pg19_text)
            positions = [
                int(text_length * 0.10),  # 10%
                int(text_length * 0.50),  # 50%
                int(text_length * 0.90),  # 90%
            ]
            
            # 如果有更多片段，在中间位置插入
            if len(fact_fragments) > 3:
                positions.extend([
                    int(text_length * 0.30),  # 30%
                    int(text_length * 0.70),  # 70%
                ])
            
            # 只使用与片段数量匹配的位置
            positions = positions[:len(fact_fragments)]
            
            # 创建插入后的文本
            result_text = pg19_text
            
            # 按位置从后往前插入，避免位置偏移问题
            insertions = list(zip(positions, fact_fragments))
            insertions.sort(reverse=True)  # 从后往前排序
            
            for pos, fragment in insertions:
                # 找到合适的插入点（在句子或段落边界）
                # 从后往前插入时，后面的插入不会影响前面的位置，所以不需要offset
                actual_pos = pos
                
                # 向前查找最近的句号、换行或段落边界
                search_start = max(0, actual_pos - 100)
                search_end = min(len(result_text), actual_pos + 100)
                search_text = result_text[search_start:search_end]
                
                # 查找插入点（优先在句号后，其次在换行后）
                insert_point = actual_pos
                for i in range(actual_pos, min(len(result_text), actual_pos + 200)):
                    if i < len(result_text):
                        if result_text[i] in '.\n':
                            insert_point = i + 1
                            break
                
                # 如果没找到合适位置，使用原始位置
                if insert_point == actual_pos:
                    # 向前查找
                    for i in range(actual_pos, max(0, actual_pos - 200), -1):
                        if i >= 0 and i < len(result_text):
                            if result_text[i] in '.\n':
                                insert_point = i + 1
                                break
                
                # 确保插入点有效
                insert_point = max(0, min(insert_point, len(result_text)))
                
                # 插入事实片段（更自然的插入方式，不添加明显标记）
                # 在段落边界插入，使其看起来像文本的一部分
                if insert_point > 0 and result_text[insert_point-1] != '\n':
                    fragment_with_context = f" {fragment}. "
                else:
                    fragment_with_context = f"\n\n{fragment}.\n\n"
                
                result_text = result_text[:insert_point] + fragment_with_context + result_text[insert_point:]
                
                logger.debug(f"[long_context_inject] Inserted fragment at position {insert_point}: {fragment[:50]}...")
            
            logger.info(f"[long_context_inject] Successfully injected {len(fact_fragments)} fragments into PG-19 text")
            logger.info(f"[long_context_inject] Result length: {len(result_text)} characters (original: {len(pg19_text)})")
            
            return result_text, True
            
        except Exception as e:
            logger.error(f"[long_context_inject] Error during injection: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return context, False
    
    # 对用户提示词进行注入
    def inject_goal(  
        self,  
        goal: str
    ) -> Tuple[str, bool]:  
        """  
        执行故障注入，并记录完整日志  
        """  

        rule = self._get_rule_by_id(self.rule_id)  
        if not rule:  
            logger.warning(f"Rule ID '{self.rule_id}' not found")  
            return goal, False

        # Inline prompt construction for goal injection (inlined from former _build_injection_prompt)
        system_intro = self.agent_intro.get("system_description", "")

        prompt = f"""
You are a fault injection engine designed to test the robustness of multi-agent systems.  
Your task is to semantically mutate user requirements according to predefined rules, while maintaining contextual coherence and fluency.  

## Agent System Description  
{system_intro}  

## Fault Injection Rule  
- **Rule ID**: {rule.get("id", "")}  
- **Rule Title**: {rule.get("title", "")}  
- **Mutation Instruction**: {rule.get("instruction", "")}  

---

## Original User Requirement  
{goal}  

---

## Task Requirements  
- **Preserve the basic structure of the question**: Maintain the syntax form and length range of the original question  
- **Introduce goal ambiguity**: Replace specific entities with generalized concepts to increase comprehension difficulty  
- **Match language style**: Keep the original expression style and tone  

## Prohibited Actions  
- Do not add any explanatory text or markers  
- Do not use prompts such as "mutated version" or "modified as"  
- Do not output a comparison between the original and mutated question  
- Do not add extra quotation marks, parentheses, or other markers  

## Output Format  
Directly output the mutated text without any additional content.  
""".strip()


        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
            )

            mutated = response.choices[0].message.content.strip()
            # 使用 Gemini API 生成内容
            # response = self.model.generate_content(
            #     prompt,
            #     generation_config=genai.types.GenerationConfig(
            #         temperature=self.temperature
            #     )
            # )

            # mutated = response.text.strip()  

            # 记录完整日志内容  
            logger.info(f"[Original Goal]\n{goal}")  
            logger.info(f"[Injection Prompt]\n{prompt}")  
            logger.info(f"[Mutated Goal]\n{mutated}")  

            if mutated and mutated != goal:  
                logger.info(f"[Result] Mutation successful: {len(goal)} → {len(mutated)} chars")  
                return mutated, True  
            else:  
                logger.warning(f"[Result] Mutation produced no change for goal")  
                return goal, False  

        except Exception as e:  
            logger.error(f"[Fault Injection] LLM call failed for goal injection: {e}")  
            return goal, False

    def inject_tool_command(
        self,
        command_json: str
    ) -> Tuple[str, bool]:
        """
        在 MetaGPT 工具调用命令中注入故障。单独变异每个命令，然后重新组合。
        
        Args:
            command_json: 原始命令 JSON 字符串，例如：
            [
                {"command_name": "Plan.append_task", "args": {...}},
                {"command_name": "RoleZero.reply_to_human", "args": {...}},
                ...
            ]
            
        Returns:
            Tuple[str, bool]: (修改后的命令 JSON 字符串, 是否成功注入)
        """
        try:
            # 解析原始命令列表
            try:
                commands = json.loads(command_json)
            except json.JSONDecodeError as e:
                logger.error(f"[Tool Command Fault] Failed to parse JSON: {e}")
                return command_json, False

            if not isinstance(commands, list):
                logger.error(f"[Tool Command Fault] Invalid format, expected list: {commands}")
                return command_json, False

            # 获取故障注入规则
            rule = self._get_rule_by_id(self.rule_id)
            if not rule:
                logger.warning(f"Rule ID '{self.rule_id}' not found")
                return command_json, False
            logger.info(f"[Tool Command Fault] rule_id: {self.rule_id}")
            # 记录命令总数
            total_commands = len(commands)
            logger.info(f"[Tool Command Fault] Found {total_commands} commands to process")
            
            # 存储变异后的命令
            mutated_commands = []
            has_mutation = False
            
            # 对每个命令单独进行变异
            for i, command in enumerate(commands):
                logger.info(f"[Tool Command Fault] Processing command {i+1}/{total_commands}")
                
                # 验证单个命令格式
                if not isinstance(command, dict) or \
                   "command_name" not in command or \
                   "args" not in command or \
                   not isinstance(command["args"], dict):
                    logger.error(f"[Tool Command Fault] Invalid command format at index {i}: {command}")
                    mutated_commands.append(command)
                    continue
                
                # 根据注入率决定是否对当前命令进行变异
                if random.random() > self.injection_rate:
                    logger.info(f"[Tool Command Fault] Skipping command {i+1} due to injection rate")
                    mutated_commands.append(command)
                    continue
                print("开始变异命令：", command)
            
                # 为单个命令构建注入提示词
                prompt = f"""
You are a tool invocation fault injection engine designed to test the robustness of multi-agent systems.  

## Agent System Introduction  
{self.tools_intro.get("system_description","")}  

## Fault Injection Rule  
- **Rule ID**: {rule.get("id", "")}  
- **Rule Title**: {rule.get("title", "")}  
- **Mutation Strategy**: {rule.get("instruction", "")}  

## Original Tool Command  
{json.dumps(command, ensure_ascii=False)}      

## Available Tool Commands  
{self.tools_intro.get("tool_categories","")}  

## Output Format  
{self.tools_intro.get("form","")}  
""".strip()
                print("变异提示词：", prompt)
                logger.info(f"[Tool Command Fault] Prompt: {prompt}")
                try:
                    # print("变异提示词：", prompt)
                    # 调用 LLM 进行变异
                    
        
                    response = self.llm_client.chat.completions.create(
                        model=self.llm_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=self.temperature,
                    )

                    mutated_str = response.choices[0].message.content.strip()
                    print("变异结果：", mutated_str)
                    # 如果是格式破坏类规则，直接保留原始字符串
                    if self.rule_id == "tool_format_error":
                        mutated_commands.append(mutated_str)  # 注意：这里是字符串，不是 dict
                        has_mutation = True
                        logger.info(f"[Tool Command Fault] Successfully mutated command {i+1}")
                        continue
                    
                    # 尝试解析LLM返回的结果
                    try:
                        mutated_command = json.loads(mutated_str)
                        if isinstance(mutated_command, dict) and \
                           "command_name" in mutated_command and \
                           "args" in mutated_command:
                            mutated_commands.append(mutated_command)
                            has_mutation = True
                            logger.info(f"[Tool Command Fault] Successfully mutated command {i+1}")
                        else:
                            logger.error(f"[Tool Command Fault] Invalid mutation result format: {mutated_str}")
                            mutated_commands.append(command)
                    except json.JSONDecodeError as e:
                        logger.error(f"[Tool Command Fault] Failed to parse mutation result: {e}")
                        mutated_commands.append(command)
                except Exception as e:
                    logger.error(f"[Tool Command Fault] Mutation failed for command {i+1}: {e}")
                    mutated_commands.append(command)
            
            
            # 只有在成功进行了至少一次变异时才返回变异后的命令
            if has_mutation:
                # 如果包含格式错误注入，直接拼接字符串列表
                if self.rule_id == "tool_format_error":
                    print("包含格式错误注入，返回字符串列表")
                    print("变异后的命令列表：", mutated_commands)
                    logger.info(f"[Tool Command Fault] Original commands:{commands}")
                    logger.info(f"[Tool Command Fault] Mutated commands:{mutated_commands}")
                    logger.info(f"[Tool Command Fault] Final mutated commands with format errors: {mutated_commands}")
                    final_output = "[\n" + ",\n".join(mutated_commands) + "\n]"
                    
                    return final_output, has_mutation
                try:
                    return json.dumps(mutated_commands, ensure_ascii=False), True
                except Exception as e:
                    logger.error(f"[Tool Command Fault] Failed to serialize mutated commands: {e}")
                    return command_json, False
            else:
                return command_json, False
                
        except Exception as e:
            logger.error(f"[Tool Command Fault] Injection failed: {e}")
            return command_json, False
def extract_json_from_text(text: str) -> Tuple[str, bool]:
    """
    从文本中提取 JSON 命令部分
    
    Args:
        text: 包含 JSON 的文本，可能包含其他描述性文本
        
    Returns:
        Tuple[str, bool]: (JSON 字符串, 是否成功提取)
    """
    try:
        # 寻找 JSON 数组的开始和结束
        start_idx = text.find('[')
        end_idx = text.rfind(']') + 1
        
        if start_idx == -1 or end_idx == 0:
            return text, False
            
        json_str = text[start_idx:end_idx].strip()
        
        # 验证提取的内容是否为有效的 JSON
        json.loads(json_str)
        return json_str, True
    except (ValueError, json.JSONDecodeError):
        return text, False

def is_tool_call_format(command_str: str) -> bool:
    """
    检查命令是否为 MetaGPT 工具调用格式
    
    Args:
        command_str: 要检查的命令字符串，可能包含其他描述性文本，例如：
        "一些描述性文本...
        
        ```json
        [
            {
                "command_name": "Plan.append_task",
                "args": {
                    "task_id": "1",
                    "instruction": "...",
                    ...
                }
            },
            ...
        ]
        ```"
        
    Returns:
        bool: 是否为有效的 MetaGPT 命令格式
    """
    try:
        # 首先尝试提取 JSON 部分
        json_str, extracted = extract_json_from_text(command_str)
        if not extracted:
            return False
            
        # 解析并验证 JSON
        commands = json.loads(json_str)
        
        # 检查是否为列表类型
        if not isinstance(commands, list):
            return False
            
        # 检查每个命令是否有必需的字段
        return all(
            isinstance(command, dict) and
            "command_name" in command and
            "args" in command and
            isinstance(command["args"], dict)
            for command in commands
        )
            
    except (json.JSONDecodeError, TypeError, KeyError):
        return False

def parse_commands_fault_injector(func: Callable):
    """装饰 parse_commands() 函数，使用LLM注入工具调用故障"""
    injection_state = {"injected": False}
    @wraps(func)
    async def wrapper(command_rsp: str, llm, exclusive_tool_commands: list[str]) -> Tuple[list[dict], bool, str]:
        try:
            # 获取配置a
            config = InjectorConfig()
            print("🐷输出看一下config")
            # 检查是否启用工具调用故障注入
            if not config.enabled or not config.tool_calling_faults.get("enabled"):
                print("🐷没有进行工具调用注入故障")
                return await func(command_rsp, llm, exclusive_tool_commands)
            if injection_state["injected"]:
                print("🐷工具调用故障已经注入过了")
                return await func(command_rsp, llm, exclusive_tool_commands)
        
            logger.info("[Tool Command Fault] Starting fault injection process")
            # 尝试从文本中提取JSON
            json_str, extracted = extract_json_from_text(command_rsp)
            if not extracted:
                logger.warning("[Tool Command Fault] No valid JSON found in command_rsp")
                return await func(command_rsp, llm, exclusive_tool_commands)
            
            logger.info(f"[Tool Command Fault] Successfully extracted JSON from text")
            
            # 验证提取的JSON是否为有效的工具调用格式
            if not is_tool_call_format(json_str):
                logger.warning("[Tool Command Fault] Extracted JSON is not in valid tool call format")
                return await func(command_rsp, llm, exclusive_tool_commands)
            
            # 初始化故障注入器
            injector = FaultInjector(config.tool_calling_faults)
            logger.info(f"[Tool Command Fault] Starting injection with rule '{config.tool_calling_faults.get('rule_id')}'")
            
            # 进行故障注入
            mutated_commands, is_mutated = injector.inject_tool_command(json_str)
            
            if is_mutated:
                logger.info("[Tool Command Fault] Injection successful")
                
                # 将变异后的JSON重新插入到原始文本中
                start_idx = command_rsp.find('[')
                end_idx = command_rsp.rfind(']') + 1
                if start_idx != -1 and end_idx != 0:
                    # 保留JSON之外的描述性文本
                    prefix = command_rsp[:start_idx]
                    suffix = command_rsp[end_idx:]
                    new_command_rsp = prefix + mutated_commands + suffix
                else:
                    new_command_rsp = mutated_commands
                logger.info(f"[Tool Command Fault] Original command_rsp: {command_rsp}")
                logger.info(f"[Tool Command Fault] New command_rsp: {new_command_rsp}")
                injection_state["injected"] = True
                return await func(new_command_rsp, llm, exclusive_tool_commands)
            else:
                logger.warning("[Tool Command Fault] Injection failed, using original command")
                return await func(command_rsp, llm, exclusive_tool_commands)
        
        except Exception as e:
            logger.error(f"[Tool Command Fault] Error during injection: {e}")
            return await func(command_rsp, llm, exclusive_tool_commands)
    return wrapper        # 添加重置方法

def team_run_input_injector():
    """Team.run() 输入故障注入装饰器，用于给用户输入注入故障"""
    injection_state = {"injected": False}

    def decorator(func: Callable):  
        @wraps(func)  
        async def wrapper(self, n_round=5, idea="", send_to="", auto_archive=True, **kwargs):  
            # 检查配置和注入状态
            config = InjectorConfig()  
            print("🐷输出看一下config")
            if not config.enabled or injection_state["injected"] or not config.input_prompt_faults.get("enabled"):  
                print("🐷没有进行输入注入故障")
                return await func(self, n_round, idea, send_to, auto_archive, **kwargs)  
            
            # 只在有用户输入时尝试注入
            if idea:  
                original_idea = idea
                try:
                    # 初始化故障注入器
                    corruption_injector = FaultInjector(config.input_prompt_faults)
                    
                    logger.info(f"[Input Fault] Starting injection with rule '{config.input_prompt_faults.get('rule_id')}'")
                    # 尝试进行故障注入
                    corrupted_idea, success = corruption_injector.inject_goal(
                        goal=original_idea
                    )
                    
                    # 记录故障注入结果
                    if success:
                        logger.info("[Input Fault] Injection successful")
                        logger.info(f"[Input Fault] Content length change: {len(original_idea)} -> {len(corrupted_idea)}")
                        logger.info(f"[Input Fault] Mutated content: {corrupted_idea[:200]}...")
                        injection_state["injected"] = True
                        idea = corrupted_idea
                    else:
                        logger.warning("[Input Fault] Injection failed, no mutation applied")
                        logger.warning(f"[Input Fault] Using original content: {original_idea[:200]}...")
                        
                    print("🐷最终使用的提示词", idea)
                    
                except Exception as e:
                    logger.error(f"[Input Fault] Error during injection: {e}")
                    logger.warning("[Input Fault] Using original input due to error")

            return await func(self, n_round, idea, send_to, auto_archive, **kwargs)
        return wrapper
    return decorator


def unified_fault_injection_decorator():  
    """  
    统一的故障注入装饰器，支持内容损坏和通信故障（互斥执行）  
      
    Args:  
        config_path: 配置文件路径  
        rule_ids: 要应用的规则 ID 列表（可选）  
      
    Usage:  
        @unified_fault_injection_decorator()  
        def _publish_message(self, message: Message, peekable: bool = True) -> bool:  
            # 原始实现  
            pass  
    """  
    """消息损坏注入装饰器 - 支持多次注入（针对特定发送者-接收者对）"""  
    # 使用字典记录每个发送者-接收者对是否已注入（支持多次注入）
    injection_state = {}  # 格式: {(sender, receiver): True/False}
    def decorator(func: Callable):  
        @wraps(func)  
        def wrapper(self, message, peekable: bool = True) -> bool:  
            # 1. 加载配置  
            config = InjectorConfig()  
            print(f"要注入的agent:{config.target_senders}")
            print(f"当前消息发送者:{message.sent_from}")
            
            # 检查是否针对特定发送者-接收者对只注入一次
            target_receiver = config.llm_injection.get("target_receiver") if config.llm_injection.get("enabled") else None
            if target_receiver and message.sent_from in config.target_senders:
                # 针对特定发送者-接收者对，检查是否已注入
                injection_key = (message.sent_from, target_receiver)
                # 注意：这里不提前返回，允许每条消息都注入
                # 如果需要只注入一次，可以取消下面的注释：
                # if injection_state.get(injection_key, False):
                #     return func(self, message, peekable)  
            # 2. 检查是否启用故障注入  
            if not config.enabled:  
                return func(self, message, peekable)  
            
            # 3. 检查是否匹配目标发送者  
            if config.target_senders and message.sent_from not in config.target_senders:  
                return func(self, message, peekable)  
              
            # 获取当前启用的 rule_id
            active_rule_id = None
            if config.llm_injection.get("enabled"):
                active_rule_id = config.llm_injection.get("rule_id")
            elif config.communication_faults.get("enabled"):
                active_rule_id = config.communication_faults.get("rule_id")
            
            logger.info(f"[Fault Injection] Triggered for message from {message.sent_from}" + (f" with rule_id: {active_rule_id}" if active_rule_id else ""))  
              
            # 4. 获取发送者角色信息  
            sender_role = None  
            if hasattr(self, 'roles') and message.sent_from in self.roles:  
                sender_role = self.roles[message.sent_from]  
              
             
              
            # 5.1 内容损坏（LLM 驱动）  
            if config.llm_injection.get("enabled"):  
                logger.info(f"[Fault Injection] Applying content corruption with rule_id: {config.llm_injection.get('rule_id')}")  
                  
                if not sender_role:  
                    logger.warning(f"[Fault Injection] Cannot find sender role for {message.sent_from}")  
                    return func(self, message, peekable)  
                
                # 检查是否有目标接收者配置（单个字符串）
                target_receiver = config.llm_injection.get("target_receiver")
                
                # 如果配置了目标接收者，检查消息是否发送给这个接收者
                if target_receiver:
                    # 检查消息的接收者中是否包含目标接收者（排除广播标记）
                    from metagpt.const import MESSAGE_ROUTE_TO_ALL
                    message_receivers = message.send_to - {MESSAGE_ROUTE_TO_ALL} if isinstance(message.send_to, set) else set()
                    
                    if target_receiver not in message_receivers:
                        logger.info(f"[Content Corruption] Message not sent to target receiver '{target_receiver}', skipping injection")
                        return func(self, message, peekable)
                    
                    # 使用目标接收者
                    receiver_name = target_receiver
                else:
                    # 没有配置目标接收者，使用原来的逻辑
                    receiver_name = None
                  
                # 创建内容损坏注入器  
                corruption_injector = FaultInjector(config.llm_injection)  
                  
                # 记录开始注入的信息
                logger.info(f"[Content Corruption] Starting injection for {message.sent_from} -> {receiver_name or 'all receivers'} with rule '{config.llm_injection.get('rule_id')}'")
                logger.info(f"[Content Corruption] Original content length: {len(message.content)}")
                logger.info(f"[Content Corruption] Original content: {message.content[:200]}...")
                
                # 应用内容损坏  
                original_content = message.content  
                corrupted_content, success = corruption_injector.inject(  
                    context=original_content,  
                    agent_name=sender_role.name,  
                    goal=sender_role.goal,
                    receiver_name=receiver_name,  # 传递接收者信息
                )  
                
                # 记录注入结果
                if success:
                    message.content = corrupted_content  
                    # 将 rule_id 添加到消息的 metadata 中
                    rule_id = config.llm_injection.get("rule_id")
                    if rule_id:
                        message.metadata["fault_injection_rule_id"] = rule_id
                    logger.info(f"[Content Corruption] Injection successful for {message.sent_from} -> {receiver_name or 'all receivers'}")
                    logger.info(f"[Content Corruption] Content length change: {len(original_content)} -> {len(corrupted_content)}")
                    logger.info(f"[Content Corruption] Mutated content: {corrupted_content[:200]}...")
                    # 记录注入状态（针对特定发送者-接收者对）
                    if receiver_name:
                        injection_key = (message.sent_from, receiver_name)
                        injection_state[injection_key] = True
                    else:
                        injection_state["injected"] = True
                else:
                    logger.warning(f"[Content Corruption] Injection failed for {message.sent_from}")
                    logger.warning(f"[Content Corruption] Using original content: {original_content[:200]}...")
               
                # 发布单个消息（可能是损坏的也可能是原始的）  
                return func(self, message, peekable)  
              
            # 5.2 通信故障（消息复制、回环等）  
            if config.communication_faults.get("enabled"):  
                logger.info("[Fault Injection] Applying communication faults")  
                
                # 应用通信故障规则  
                messages = [message]  
                rule_id = config.communication_faults.get("rule_id")  
                logger.info(f"[Communication Fault] rule_id: {rule_id}")
                
                # 将 rule_id 添加到原始消息的 metadata 中
                if rule_id:
                    message.metadata["fault_injection_rule_id"] = rule_id
                
                if rule_id == "message_duplication_storm":  
                    duplicates = [message.model_copy(deep=True) for _ in range(1000)]  
                    # 确保所有副本都包含 rule_id
                    for dup_msg in duplicates:
                        if rule_id:
                            dup_msg.metadata["fault_injection_rule_id"] = rule_id
                    messages.extend(duplicates)  
                    logger.warning(f"[Communication Fault] Applied {rule_id}: created {len(duplicates)} duplicates")  
                    # 延迟堆积
                elif rule_id == "echo_loop_injection": 
                    if message.send_to and message.sent_from:
                        # 回环一次
                        for _ in range(1):  # 堆积5次，可改为你想要的次数
                            echo_msg = message.model_copy(deep=True)
                            # 确保回环消息也包含 rule_id
                            if rule_id:
                                echo_msg.metadata["fault_injection_rule_id"] = rule_id
                            echo_msg.send_to = {message.sent_from}
                            echo_msg.sent_from = list(message.send_to)[0] if message.send_to else message.sent_from
                            messages.append(echo_msg)
                        logger.warning(f"[Communication Fault] Applied {rule_id}: created 1 echo loops")
                    # 冗余信息                 
                elif rule_id == "broadcast_amplification":  
                    print("🐷🐷进行广播注入故障")
                    from metagpt.const import MESSAGE_ROUTE_TO_ALL  
                    # 将任何消息转换为广播消息
                    if not isinstance(message.send_to, set):
                        message.send_to = {message.send_to} if message.send_to else set()
                    # 记录原始接收者
                    original_recipients = message.send_to.copy()
                    # 添加广播标记
                    message.send_to.add(MESSAGE_ROUTE_TO_ALL)
                    logger.warning(f"[Communication Fault] Converting private message to broadcast. Original recipients: {original_recipients}, Now: {message.send_to}")  
                # 命令重复注入
                elif rule_id == "command_repetition":  
                    if "append_task" in message.content or "finish_current_task" in message.content:  
                        duplicates = [message.model_copy(deep=True) for _ in range(3)]  
                        # 确保所有副本都包含 rule_id
                        for dup_msg in duplicates:
                            if rule_id:
                                dup_msg.metadata["fault_injection_rule_id"] = rule_id
                        messages.extend(duplicates)  
                        logger.warning(f"[Communication Fault] Applied {rule_id}: repeated command")  
                  
                # 发布所有消息  
                results = []  
                for msg in messages:  
                    result = func(self, msg, peekable)  
                    results.append(result) 
                # 不要二次注入故障 
                injection_state["injected"] = True
                  
                return all(results)  
              
            # 6. 如果都没启用，正常发布  
            return func(self, message, peekable)  
          
        return wrapper  
    return decorator

# 为了冗余信息，进行广播📢
def enable_broadcast(message: Message) -> Message:
    """启用消息的广播功能"""
    from metagpt.const import MESSAGE_ROUTE_TO_ALL
    if not isinstance(message.send_to, set):
        message.send_to = {message.send_to} if message.send_to else set()
    message.send_to.add(MESSAGE_ROUTE_TO_ALL)
    return message

