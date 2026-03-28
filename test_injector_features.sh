#!/bin/bash

# 测试脚本：验证 run_tasks_injector.sh 的功能
# 包括：断点续传、超时检测、重试机制

set -e

echo "=========================================="
echo "测试 run_tasks_injector.sh 功能"
echo "=========================================="
echo ""

# 测试目录
TEST_DIR="./test_injector_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$TEST_DIR"
cd "$TEST_DIR"

echo "测试目录: $TEST_DIR"
echo ""

# 1. 测试断点续传功能
echo "----------------------------------------"
echo "测试 1: 断点续传功能"
echo "----------------------------------------"

# 创建模拟状态文件
STATE_FILE="./run_tasks_reasoning-anomaly-injection.state"
echo "0" > "$STATE_FILE"
echo "1" >> "$STATE_FILE"
echo "5" >> "$STATE_FILE"

echo "创建状态文件: $STATE_FILE"
echo "内容:"
cat "$STATE_FILE"
echo ""

# 模拟 load_completed_tasks 函数
load_completed_tasks() {
  local state_file="$1"
  local -n completed_array="$2"
  completed_array=()
  
  if [ -f "$state_file" ]; then
    while IFS= read -r line; do
      [[ -n "$line" ]] && completed_array+=("$line")
    done < "$state_file"
  fi
}

# 模拟 is_task_completed 函数
is_task_completed() {
  local task_idx="$1"
  local -n completed_array="$2"
  for completed in "${completed_array[@]}"; do
    if [[ "$completed" == "$task_idx" ]]; then
      return 0
    fi
  done
  return 1
}

# 测试任务列表
TEST_TASKS=(0 1 2 3 4 5 6)

COMPLETED_TASKS=()
load_completed_tasks "$STATE_FILE" COMPLETED_TASKS

echo "已完成的任务: ${COMPLETED_TASKS[*]}"
echo ""

SKIPPED=0
for task in "${TEST_TASKS[@]}"; do
  if is_task_completed "$task" COMPLETED_TASKS; then
    echo "✓ 任务 $task 已跳过（在状态文件中）"
    ((SKIPPED++))
  else
    echo "→ 任务 $task 需要执行"
  fi
done

echo ""
echo "预期跳过: 3 个任务 (0, 1, 5)"
echo "实际跳过: $SKIPPED 个任务"
if [ $SKIPPED -eq 3 ]; then
  echo "✓ 测试通过：断点续传功能正常"
else
  echo "✗ 测试失败：跳过的任务数量不正确"
fi
echo ""

# 2. 测试状态文件去重
echo "----------------------------------------"
echo "测试 2: 状态文件去重功能"
echo "----------------------------------------"

# 模拟 save_completed_task 函数（带去重）
save_completed_task() {
  local state_file="$1"
  local task_idx="$2"
  
  if [ -f "$state_file" ] && grep -q "^${task_idx}$" "$state_file"; then
    return 0
  fi
  
  echo "$task_idx" >> "$state_file"
}

TEST_STATE="./test_state.txt"
rm -f "$TEST_STATE"

echo "添加任务 1"
save_completed_task "$TEST_STATE" "1"
echo "添加任务 2"
save_completed_task "$TEST_STATE" "2"
echo "再次添加任务 1（应该被忽略）"
save_completed_task "$TEST_STATE" "1"
echo "添加任务 3"
save_completed_task "$TEST_STATE" "3"

echo ""
echo "状态文件内容:"
cat "$TEST_STATE"
echo ""

COUNT=$(wc -l < "$TEST_STATE" | tr -d ' ')
if [ "$COUNT" -eq 3 ]; then
  echo "✓ 测试通过：状态文件去重功能正常（共 $COUNT 行，无重复）"
else
  echo "✗ 测试失败：状态文件有重复条目（共 $COUNT 行，预期 3 行）"
fi
echo ""

# 3. 测试超时检测逻辑（模拟）
echo "----------------------------------------"
echo "测试 3: 超时检测逻辑（模拟）"
echo "----------------------------------------"

TIMEOUT_SECONDS=10  # 测试用短超时
LOG_FILE="./test_timeout.log"
rm -f "$LOG_FILE"

echo "模拟任务执行（每2秒输出一次，持续30秒）"
echo "超时设置: ${TIMEOUT_SECONDS}秒"
echo ""

# 模拟一个会持续输出的任务
(
  for i in {1..15}; do
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 任务输出 $i" >> "$LOG_FILE"
    sleep 2
  done
) &
TASK_PID=$!

# 模拟监控进程
(
  local last_log_size=0
  local last_update_time=$(date +%s)
  
  while kill -0 "$TASK_PID" 2>/dev/null; do
    sleep 2
    local current_time=$(date +%s)
    
    if [ -f "$LOG_FILE" ]; then
      local current_log_size=$(stat -f %z "$LOG_FILE" 2>/dev/null || stat -c %s "$LOG_FILE" 2>/dev/null || echo 0)
      
      if [ "$current_log_size" -gt "$last_log_size" ]; then
        last_log_size=$current_log_size
        last_update_time=$current_time
        echo "  [监控] 检测到日志更新 (大小: $current_log_size)"
      else
        local time_since_update=$((current_time - last_update_time))
        echo "  [监控] 无更新，已等待 ${time_since_update}秒"
        
        if [ "$time_since_update" -ge "$TIMEOUT_SECONDS" ]; then
          echo "  [监控] ⚠ 超时检测触发！"
          kill -TERM "$TASK_PID" 2>/dev/null || true
          break
        fi
      fi
    fi
  done
) &
MONITOR_PID=$!

wait "$TASK_PID" 2>/dev/null || true
kill "$MONITOR_PID" 2>/dev/null || true
wait "$MONITOR_PID" 2>/dev/null || true

echo ""
echo "日志文件最后几行:"
tail -5 "$LOG_FILE" 2>/dev/null || echo "（无日志）"
echo ""

if grep -q "超时检测触发" <<< "$(jobs 2>&1 || echo '')" || [ ! -f "$LOG_FILE" ] || [ ! -s "$LOG_FILE" ]; then
  echo "✓ 测试通过：超时检测逻辑正常（任务被正确监控）"
else
  echo "⚠ 注意：此测试需要实际运行才能完全验证超时功能"
fi
echo ""

# 清理
echo "----------------------------------------"
echo "清理测试文件"
echo "----------------------------------------"
cd ..
# rm -rf "$TEST_DIR"  # 取消注释以自动清理
echo "测试目录保留在: $TEST_DIR"
echo "（可以手动检查后删除）"
echo ""

echo "=========================================="
echo "测试完成"
echo "=========================================="

