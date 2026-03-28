# 高并发测试脚本使用说明

## 概述

`run_tasks_concurrent.sh` 是一个支持高并发执行任务的脚本，用于测试系统在并发情况下的表现，找出并发相关的错误。

## 使用方法

### 基本用法

```bash
# 使用默认并发数（5个并发任务）
cd MetaGPT
./run_tasks_concurrent.sh
```

### 自定义并发数

```bash
# 设置并发数为 10
MAX_CONCURRENT=10 ./run_tasks_concurrent.sh

# 设置并发数为 20（更激进的测试）
MAX_CONCURRENT=20 ./run_tasks_concurrent.sh
```

### 指定故障注入规则

```bash
# 只测试特定规则
./run_tasks_concurrent.sh message_duplication_storm

# 测试多个规则
./run_tasks_concurrent.sh message_duplication_storm broadcast_amplification
```

### 组合使用

```bash
# 高并发测试特定规则
MAX_CONCURRENT=15 ./run_tasks_concurrent.sh message_duplication_storm
```

## 并发数建议

- **保守测试**: `MAX_CONCURRENT=3` - 适合初步测试
- **正常测试**: `MAX_CONCURRENT=5` - 默认值，平衡性能和稳定性
- **压力测试**: `MAX_CONCURRENT=10` - 测试中等压力
- **极限测试**: `MAX_CONCURRENT=20+` - 测试系统极限，可能触发各种错误

## 输出说明

脚本会创建以下目录结构：

```
concurrent_logs_<rule_id>_<timestamp>/
├── main.log                    # 主日志文件，包含所有任务的执行摘要
├── task_0.log                  # 任务 0 的详细日志
├── task_0.result               # 任务 0 的执行结果（退出码、耗时等）
├── task_1.log
├── task_1.result
└── ...
```

## 监控并发执行

脚本会实时输出：
- 当前运行的并发任务数
- 已完成任务数/总任务数
- 成功/失败统计
- 每个任务的执行时间

## 错误分析

当任务失败时，脚本会：
1. 在主日志中标记失败的任务
2. 显示失败任务的最后 50 行日志
3. 所有详细错误信息保存在对应的 `task_<idx>.log` 文件中

## 注意事项

1. **资源消耗**: 高并发会消耗大量 CPU、内存和 API 配额
2. **API 限流**: 如果遇到 429 错误（Rate Limit），需要降低并发数或增加延迟
3. **文件冲突**: 每个任务使用独立的项目路径（`<project_path>_task_<idx>`），避免文件冲突
4. **日志大小**: 高并发会产生大量日志，注意磁盘空间

## 示例输出

```
========================================
=== 使用故障注入规则: message_duplication_storm (并发数: 10)
========================================
2025-01-XX XX:XX:XX - [主进程] 启动任务 0 (当前并发: 0/10)
2025-01-XX XX:XX:XX - [主进程] 启动任务 1 (当前并发: 1/10)
...
2025-01-XX XX:XX:XX - [主进程] 进度: 5/160 (成功: 3, 失败: 2, 运行中: 10)
```

## 故障排查

如果遇到问题：

1. **查看主日志**: `cat concurrent_logs_<rule>_<timestamp>/main.log`
2. **查看特定任务日志**: `cat concurrent_logs_<rule>_<timestamp>/task_<idx>.log`
3. **检查系统资源**: `top` 或 `htop` 查看 CPU/内存使用
4. **降低并发数**: 如果频繁出错，尝试降低 `MAX_CONCURRENT`



































