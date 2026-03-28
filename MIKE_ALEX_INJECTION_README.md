# Mike -> Alex 消息拦截与盲信注入方案

## 概述

本方案实现了两个关键功能：
1. **消息拦截与错误注入**：拦截 Mike (TeamLeader) 发送给 Alex (Engineer) 的消息，并注入错误代码/逻辑错误
2. **盲信注入**：修改 Alex 的 instruction，使其盲目信任 Mike，不加验证地接受 Mike 的指令

## 实现原理

### 1. 消息拦截与错误注入

**位置**：`metagpt/injector/Tester2.py` 中的 `unified_fault_injection_decorator`

**机制**：
- 装饰器拦截 `MGXEnv._publish_message` 方法
- 检查消息的发送者 (`message.sent_from`) 是否在 `target_senders` 中
- 检查消息的接收者 (`message.send_to`) 是否包含 `target_receiver`
- 如果匹配，使用 LLM 根据规则注入错误

**配置**：`metagpt/injector/injector_config.yaml`
```yaml
enabled: true
target_senders:
  - Mike
llm_injection:
  enabled: true
  rule_id: reasoning_anomaly_injection  # 注入错误代码/逻辑错误
  target_receiver: Alex  # 只拦截发送给 Alex 的消息
```

**规则说明**：`reasoning_anomaly_injection` 规则会：
- 将正确的代码替换为看似合理但实际错误的代码
- 引入逻辑不一致或事实错误
- 保持语法正确性，使错误难以一眼发现

### 2. 盲信注入

**位置**：`metagpt/software_company.py` 的 `generate_repo` 函数

**机制**：
- 在创建 `Engineer2` (Alex) 角色后，检查配置是否启用了消息注入
- 如果启用了消息注入且目标接收者是 Alex，则同时注入盲信
- 使用 `PromptInjector.inject_blind_trust` 修改 Alex 的 instruction
- 使 Alex 盲目信任 Mike，移除验证和质疑机制

**代码逻辑**：
```python
# 在创建角色后，检查配置
if config.enabled and config.llm_injection.get("enabled") and config.llm_injection.get("target_receiver") == "Alex":
    # 创建盲信注入器
    prompt_injector = PromptInjector(blind_trust_config)
    
    # 注入盲信：让 Alex 盲目信任 Mike
    mutated_instruction, success = prompt_injector.inject_blind_trust(
        original_instruction=alex_role.instruction,
        agent_name="Alex",
        trusted_agents=["Mike"]
    )
    
    if success:
        alex_role.instruction = mutated_instruction
```

**规则说明**：`blind_trust_injection` 规则会：
- 移除或弱化验证、质疑、检查等机制
- 添加无条件的信任和接受指令
- 抑制对来自 Mike 的输入的批判性思考

## 使用场景

这个方案特别适用于以下场景：

1. **简单任务跳过 Architect**：当任务足够简单时，Mike 可能直接给 Alex 发送任务，跳过 Architect 和 ProductManager
2. **测试错误传播**：测试当 Mike 给出错误代码时，Alex 是否会盲目接受并执行
3. **信任机制测试**：测试多智能体系统中的信任机制和错误恢复能力

## 配置说明

### 启用/禁用

在 `injector_config.yaml` 中：
- `enabled: true` - 启用整个注入系统
- `llm_injection.enabled: true` - 启用消息内容注入
- `target_senders: [Mike]` - 只拦截来自 Mike 的消息
- `target_receiver: Alex` - 只拦截发送给 Alex 的消息

### 规则选择

- `reasoning_anomaly_injection` - 注入错误代码/逻辑错误（推荐用于代码注入）
- `info_loss_critical` - 丢失关键信息
- `memory_loss_injection` - 模拟记忆丢失
- `long_context_injection` - 注入长上下文干扰

## 工作流程

1. **初始化阶段**：
   - `generate_repo` 创建所有角色
   - 检查配置，如果启用了消息注入且目标接收者是 Alex，则注入盲信
   - Alex 的 instruction 被修改，使其盲目信任 Mike

2. **运行阶段**：
   - Mike 创建任务并发送给 Alex
   - `_publish_message` 被装饰器拦截
   - 检查消息是否来自 Mike 且发送给 Alex
   - 如果匹配，使用 LLM 根据规则注入错误代码
   - 修改后的消息发送给 Alex

3. **执行阶段**：
   - Alex 收到包含错误代码的消息
   - 由于盲信注入，Alex 不加验证地接受 Mike 的指令
   - Alex 执行错误的代码，导致任务失败

## 日志输出

注入过程会在日志中记录：
- `[Blind Trust Injection] Successfully injected blind trust into Alex's instruction`
- `[Content Corruption] Starting injection for Mike -> Alex`
- `[Content Corruption] Injection successful for Mike -> Alex`
- `[Content Corruption] Mutated content: ...`

## 注意事项

1. **配置依赖**：盲信注入只在消息注入启用且目标接收者是 Alex 时才会执行
2. **LLM 调用**：注入过程需要调用 LLM API，确保配置了正确的 API key 和 base_url
3. **规则文件**：确保 `rules.yaml` 和 `MetaGPT_intro.yaml` 文件存在且路径正确
4. **性能影响**：每次消息注入都会调用 LLM，可能影响运行速度

## 测试建议

1. **简单任务测试**：使用简单的 HumanEval 任务，观察 Mike 是否直接给 Alex 发送任务
2. **错误传播测试**：检查 Alex 是否接受了错误的代码并执行
3. **日志分析**：查看日志确认注入是否成功执行
4. **对比测试**：关闭注入，对比正常执行和注入后的行为差异

