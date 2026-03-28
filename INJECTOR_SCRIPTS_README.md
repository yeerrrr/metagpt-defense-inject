# 故障注入脚本说明

## 概述

已将原来的 `run_tasks_injector.sh` 拆分为12个独立的脚本，每个脚本对应一个故障注入规则，使用不同的项目路径，可以并发运行。

## 脚本列表

| 脚本 | 规则 | Section | 项目路径 |
|------|------|---------|----------|
| `run_tasks_injector_1_message_duplication_storm.sh` | message_duplication_storm | communication_faults | ./humaneval_baseline-1 |
| `run_tasks_injector_2_broadcast_amplification.sh` | broadcast_amplification | communication_faults | ./humaneval_baseline-2 |
| `run_tasks_injector_3_echo_loop_injection.sh` | echo_loop_injection | communication_faults | ./humaneval_baseline-3 |
| `run_tasks_injector_4_weak_parameter_filling.sh` | weak_parameter_filling | tool_calling_faults | ./humaneval_baseline-4 |
| `run_tasks_injector_5_tool_format_error.sh` | tool_format_error | tool_calling_faults | ./humaneval_baseline-5 |
| `run_tasks_injector_6_info_loss_critical.sh` | info_loss_critical | llm_injection | ./humaneval_baseline-6 |
| `run_tasks_injector_7_wrong_tool_selection.sh` | wrong_tool_selection | tool_calling_faults | ./humaneval_baseline-7 |
| `run_tasks_injector_8_logic_conflict.sh` | logic_conflict | input_prompt_faults | ./humaneval_baseline-8 |
| `run_tasks_injector_9_goal_unclear.sh` | goal_unclear | input_prompt_faults | ./humaneval_baseline-9 |
| `run_tasks_injector_10_reasoning_anomaly_injection.sh` | reasoning_anomaly_injection | llm_injection | ./humaneval_baseline-10 |
| `run_tasks_injector_11_unexecutable_plan_generation.sh` | unexecutable_plan_generation | llm_injection | ./humaneval_baseline-11 |
| `run_tasks_injector_12_memory_loss_injection.sh` | memory_loss_injection | llm_injection | ./humaneval_baseline-12 |

## 使用方法

### 方法1: 并发运行所有脚本

```bash
./run_all_injectors_parallel.sh
```

这个脚本会在后台启动所有12个脚本，并等待它们全部完成。

### 方法2: 单独运行某个脚本

```bash
./run_tasks_injector_1_message_duplication_storm.sh
./run_tasks_injector_2_broadcast_amplification.sh
# ... 等等
```

### 方法3: 手动并发运行

```bash
# 在后台启动所有脚本
./run_tasks_injector_1_message_duplication_storm.sh &
./run_tasks_injector_2_broadcast_amplification.sh &
./run_tasks_injector_3_echo_loop_injection.sh &
./run_tasks_injector_4_weak_parameter_filling.sh &
./run_tasks_injector_5_tool_format_error.sh &
./run_tasks_injector_6_info_loss_critical.sh &
./run_tasks_injector_7_wrong_tool_selection.sh &
./run_tasks_injector_8_logic_conflict.sh &
./run_tasks_injector_9_goal_unclear.sh &
./run_tasks_injector_10_reasoning_anomaly_injection.sh &
./run_tasks_injector_11_unexecutable_plan_generation.sh &
./run_tasks_injector_12_memory_loss_injection.sh &

# 等待所有后台任务完成
wait
```

## 监控

### 查看运行中的进程

```bash
ps aux | grep run_tasks_injector | grep -v grep
```

### 查看日志文件

```bash
# 按时间排序查看最新的日志文件
ls -lt run_tasks_*.log | head -12
```

### 查看特定脚本的日志

每个脚本会生成独立的日志文件，格式为：
```
run_tasks_<rule_id>_YYYYMMDD_HHMMSS.log
```

## 注意事项

1. **项目路径隔离**: 每个脚本使用独立的项目路径（-1到-12），避免文件冲突
2. **配置文件**: 所有脚本共享同一个配置文件 `metagpt/injector/injector_config.yaml`，但每个脚本会独立设置其规则
3. **特殊处理**: `memory_loss_injection` 规则会自动设置 `target_receiver` 为 "Alex"
4. **资源使用**: 并发运行12个脚本会消耗大量资源，请确保系统有足够的CPU和内存
5. **日志管理**: 每个脚本生成独立的日志文件，便于追踪和调试

## 任务列表

所有脚本使用相同的任务列表：
- 任务范围: 0-163
- 排除任务: 75, 116, 129, 145
- 总任务数: 160

