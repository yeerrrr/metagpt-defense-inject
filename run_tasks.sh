#!/bin/bash

set -euo pipefail

# 任务列表 - 这些是要执行的HumanEval任务索引
TASKS=()
EXCLUDED_TASKS=(75 116 129 145)
for i in {139..163}; do
  exclude=false
  for excluded in "${EXCLUDED_TASKS[@]}"; do
    if [ "$i" -eq "$excluded" ]; then
      exclude=true
      break
    fi
  done
  if [ "$exclude" = false ]; then
    TASKS+=("$i")
  fi
done
# 项目路径
PROJECT_PATH="/Users/ximenajia/CODE/Tester/MetaGPT/humaneval_baseline"

# 超时设置（秒）- 4分钟
TIMEOUT_SECONDS=240

# 停滞监控设置（秒）
# 如果任务超过此时间没有日志更新，会尝试自动回答
STALL_WARNING_SECONDS=60   # 1分钟无更新则尝试自动回答
STALL_CHECK_INTERVAL=10    # 每10秒检查一次
STALL_TIMEOUT_SECONDS=240  # 4分钟无更新则直接跳过任务

# Rate Limit 控制：任务之间的延迟间隔（秒）
# 避免 API 请求过于频繁导致 429 错误（Rate Limit Exceeded）
# 建议值：2-5 秒，根据 API 服务商的限制调整
TASK_DELAY_SECONDS=5

# 日志文件（使用固定名称以支持断点续传）
LOG_FILE="./run_tasks.log"

# 状态文件（记录已执行的任务，无论成功或失败）
STATE_FILE="./run_tasks.state"

# 回答次数跟踪文件
REPLY_COUNT_FILE="./run_tasks_reply_count.txt"

# 临时文件目录
TMP_DIR="./.tmp"

# 提取日志中的 REQUIREMENT 和 ask_human 问题，并生成回答
generate_auto_reply() {
  local log_file="$1"
  local task_idx="$2"
  
  # 使用 Python 提取信息并调用 API
  python3 - "$log_file" "$task_idx" <<'PYTHON_SCRIPT'
import sys
import re
import json
import os
from pathlib import Path

log_file = sys.argv[1]
task_idx = sys.argv[2]

try:
    # 确保路径是绝对路径
    if not os.path.isabs(log_file):
        log_file = os.path.abspath(log_file)
    
    # 检查文件是否存在
    if not os.path.exists(log_file):
        print(f"Error: Log file not found: {log_file}", file=sys.stderr)
        sys.exit(1)
    
    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    if not lines:
        print(f"Error: Log file is empty: {log_file}", file=sys.stderr)
        sys.exit(1)
    
    # 提取 [REQUIREMENT] 部分
    requirement = ""
    in_requirement = False
    requirement_lines = []
    consecutive_empty = 0
    
    for i, line in enumerate(lines):
        if '[REQUIREMENT]' in line:
            in_requirement = True
            consecutive_empty = 0
            req_start = line.find('[REQUIREMENT]') + len('[REQUIREMENT]')
            remaining = line[req_start:].strip()
            if remaining:
                requirement_lines.append(remaining)
            continue
        
        if in_requirement:
            if re.match(r'^\d{4}-\d{2}-\d{2}', line.strip()):
                break
            
            if not line.strip():
                consecutive_empty += 1
                if consecutive_empty >= 2 and requirement_lines:
                    if i + 1 < len(lines) and re.match(r'^\d{4}-\d{2}-\d{2}', lines[i + 1].strip()):
                        break
                requirement_lines.append("")
            else:
                consecutive_empty = 0
                requirement_lines.append(line.rstrip())
    
    requirement = '\n'.join(requirement_lines).strip()
    
    # 提取最后一个 RoleZero.ask_human 的问题
    question = ""
    ask_human_positions = []
    for i, line in enumerate(lines):
        if 'RoleZero.ask_human' in line:
            ask_human_positions.append(i)
    
    if ask_human_positions:
        start_idx = ask_human_positions[-1]
        search_text = '\n'.join(lines[start_idx:min(start_idx + 50, len(lines))])
        pattern = r"'question':\s*'((?:[^'\\]|\\.|''|\\n)*?)'\s*[,\}]"
        match = re.search(pattern, search_text, re.DOTALL)
        
        if match:
            question = match.group(1)
            question = question.replace("\\n", "\n")
            question = question.replace("''", "'")
            question = question.replace("\\'", "'")
            question = question.replace("\\\\", "\\")
            question = question.rstrip("\\")
    
    # 检查是否有足够的信息生成回答
    if not requirement and not question:
        print("Error: No requirement or question found in log file", file=sys.stderr)
        sys.exit(1)
    
    # 构建提示词
    prompt_parts = []
    if requirement:
        prompt_parts.append(f"Original Requirement:\n{requirement}")
    if question:
        prompt_parts.append(f"Question:\n{question}")
    
    prompt = f"""You are helping to answer a clarification question from a software development agent. The agent is asking for clarification to proceed with implementation.

{chr(10).join(prompt_parts)}

IMPORTANT INSTRUCTIONS:
1. Answer the question DIRECTLY and CONCISELY - do NOT state facts or describe what has been done
2. If asked about filename, provide the exact filename (e.g., "rolling_max.py" or "something.py")
3. If asked about imports, answer "yes" or "no" and what to import
4. If asked about data types, specify the type (e.g., "integers only" or "any comparable items")
5. Keep your answer to ONE line and be direct - just answer the question, don't explain or describe actions
6. Based on the original requirement, infer the correct answer if the question is about ambiguous parts

Provide a concise one-line English answer that directly addresses the question:"""
    
    # 调用API
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key="sk-WFgG3qVdjiTOPeMM8XGPSEcVFDvhrx70n2X1TLZoehx2adiL",
            base_url="https://yunwu.ai/v1",
        )
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that provides direct, concise one-line English answers to clarification questions. Answer the question directly - do NOT describe what has been done or state facts. Just provide the answer the agent needs to proceed."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=4096,
            timeout=30
        )
        
        if not response or not response.choices or not response.choices[0].message or not response.choices[0].message.content:
            print("Error: Invalid API response", file=sys.stderr)
            sys.exit(1)
        
        answer = response.choices[0].message.content.strip()
        if not answer:
            print("Error: Answer is empty", file=sys.stderr)
            sys.exit(1)
        
        # 确保回答只有一行
        answer = answer.split('\n')[0].strip()
        if not answer:
            print("Error: Answer is empty after splitting", file=sys.stderr)
            sys.exit(1)
        
        sys.stdout.write(answer + '\n')
        sys.stdout.flush()
        sys.exit(0)
        
    except Exception as api_error:
        print(f"Error: API call failed: {api_error}", file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print(f"Error generating reply: {e}", file=sys.stderr)
    sys.exit(1)
PYTHON_SCRIPT
}

# 回答次数跟踪文件路径
get_reply_count_file() {
  echo "./run_tasks_reply_count.txt"
}

# 获取任务ID的回答次数
get_reply_count() {
  local task_idx="$1"
  local count_file="$2"
  if [ -f "$count_file" ]; then
    grep "^${task_idx}:" "$count_file" 2>/dev/null | cut -d':' -f2 || echo "0"
  else
    echo "0"
  fi
}

# 增加任务ID的回答次数
increment_reply_count() {
  local task_idx="$1"
  local count_file="$2"
  local current_count=$(get_reply_count "$task_idx" "$count_file")
  local new_count=$((current_count + 1))
  
  if [ -f "$count_file" ]; then
    if grep -q "^${task_idx}:" "$count_file" 2>/dev/null; then
      sed -i.bak "s/^${task_idx}:.*/${task_idx}:${new_count}/" "$count_file" 2>/dev/null || \
      sed -i '' "s/^${task_idx}:.*/${task_idx}:${new_count}/" "$count_file" 2>/dev/null
      rm -f "${count_file}.bak" 2>/dev/null
    else
      echo "${task_idx}:${new_count}" >> "$count_file"
    fi
  else
    echo "${task_idx}:${new_count}" > "$count_file"
  fi
  
  echo "$new_count"
}

# 执行任务并监控超时和停滞
# 监控主日志文件 run_tasks.log，如果超过超时时间没有更新，则终止任务
# 如果检测到停滞且存在 ask_human，则尝试自动回答
run_task_with_timeout() {
  local task_idx="$1"
  local main_log_file="$2"  # 主日志文件 run_tasks.log
  local project_path="$3"
  local timeout_seconds="$4"
  
  # 创建临时文件目录（如果不存在）
  mkdir -p "$TMP_DIR"
  
  # 记录任务开始时间和初始日志大小
  local task_start_time=$(date +%s)
  local last_update_time=$task_start_time
  local task_pid=""
  local monitor_pid=""
  local timeout_flag_file="${TMP_DIR}/timeout_flag_${task_idx}.tmp"
  
  # 获取主日志文件的初始大小
  local initial_log_size=0
  if [ -f "$main_log_file" ]; then
    initial_log_size=$(stat -f %z "$main_log_file" 2>/dev/null || stat -c %s "$main_log_file" 2>/dev/null || echo 0)
  fi
  
  # 启动任务（后台运行）
  # 使用临时文件保存退出码，确保能正确捕获
  local exit_code_file="${TMP_DIR}/exit_code_${task_idx}.tmp"
  (
    # 任务输出同时写入主日志文件
    python main.py "$task_idx" --project-path "$project_path" 2>&1 | tee -a "$main_log_file"
    echo $? > "$exit_code_file"
  ) &
  task_pid=$!
  
  # 启动监控进程（监控主日志文件 run_tasks.log 的更新）
  (
    local last_log_size=$initial_log_size
    local reply_count_file=$(get_reply_count_file)
    local warning_sent=false
    
    while kill -0 "$task_pid" 2>/dev/null; do
      sleep "$STALL_CHECK_INTERVAL"
      local current_time=$(date +%s)
      
      # 检查主日志文件大小是否有变化
      if [ -f "$main_log_file" ]; then
        local current_log_size=$(stat -f %z "$main_log_file" 2>/dev/null || stat -c %s "$main_log_file" 2>/dev/null || echo 0)
        
        if [ "$current_log_size" -gt "$last_log_size" ]; then
          # 日志有更新，重置计时
          last_log_size=$current_log_size
          last_update_time=$current_time
          warning_sent=false
        else
          # 检查是否超时（主日志文件超过超时时间没有更新）
          local time_since_update=$((current_time - last_update_time))
          
          if [ "$time_since_update" -ge "$timeout_seconds" ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') - ⚠ 任务 $task_idx 超时（主日志文件 ${timeout_seconds}秒无更新），正在终止并跳到下一个任务..." | tee -a "$main_log_file"
            touch "$timeout_flag_file"
            kill -TERM "$task_pid" 2>/dev/null || true
            sleep 5
            kill -KILL "$task_pid" 2>/dev/null || true
            exit 0
          elif [ "$time_since_update" -ge "$STALL_WARNING_SECONDS" ] && [ "$warning_sent" = false ]; then
            # 检测到停滞，尝试自动回答
            warning_sent=true
            
            # 检查日志中是否有 ask_human
            if grep -q "RoleZero.ask_human" "$main_log_file" 2>/dev/null; then
              # 检查回答次数
              local reply_count=$(get_reply_count "$task_idx" "$reply_count_file")
              
              if [ "$reply_count" -lt 2 ]; then
                # 尝试自动生成回答
                if command -v python3 > /dev/null 2>&1; then
                  echo "🤖 检测到停滞且存在 ask_human，尝试自动生成回答..." | tee -a "$main_log_file"
                  
                  # 查找任务日志文件
                  local task_log_dir="${project_path}/logs"
                  local task_log_file=""
                  
                  if [ -d "$task_log_dir" ]; then
                    task_log_file=$(find "$task_log_dir" -maxdepth 1 -name "${task_idx}_*.log" -type f | head -n 1)
                  fi
                  
                  if [ -z "$task_log_file" ] || [ ! -f "$task_log_file" ]; then
                    task_log_file="$main_log_file"
                  fi
                  
                  # 生成自动回答
                  local temp_stdout="${TMP_DIR}/stdout_${task_idx}.tmp"
                  local temp_stderr="${TMP_DIR}/stderr_${task_idx}.tmp"
                  local exit_code=0
                  generate_auto_reply "$task_log_file" "$task_idx" > "$temp_stdout" 2> "$temp_stderr" || exit_code=$?
                  
                  if [ $exit_code -eq 0 ]; then
                    local auto_reply=$(cat "$temp_stdout" 2>/dev/null | tail -n 1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
                    
                    if [ -n "$auto_reply" ] && [ ${#auto_reply} -gt 0 ]; then
                      # 验证回答不是错误信息
                      if ! echo "$auto_reply" | grep -qiE "(error|traceback|exception|failed|missing|not found)"; then
                        # 将回答写入日志文件
                        {
                          echo ""
                          echo "[AUTO_REPLY] $(date '+%Y-%m-%d %H:%M:%S')"
                          echo "$auto_reply"
                          echo "[END_AUTO_REPLY]"
                          echo ""
                        } >> "$main_log_file"
                        
                        # 尝试找到主进程并向其发送回答
                        local main_pid=$(pgrep -f "python.*main\.py.*$task_idx.*--project-path" | head -n 1)
                        
                        if [ -n "${TMUX:-}" ] && [ -n "$main_pid" ]; then
                          local tmux_target="${TMUX_PANE:-}"
                          if [ -z "$tmux_target" ]; then
                            tmux_target=$(tmux list-panes -a -F "#{pane_id} #{pane_pid}" 2>/dev/null | grep " $main_pid$" | cut -d' ' -f1 | head -n 1)
                          fi
                          
                          if [ -n "$tmux_target" ]; then
                            local escaped_reply=$(echo "$auto_reply" | sed "s/'/'\\\\''/g")
                            tmux send-keys -t "$tmux_target" "$escaped_reply" Enter 2>/dev/null && {
                              echo "📤 已通过 tmux 向主进程发送回答 (PID: $main_pid)" | tee -a "$main_log_file"
                            }
                          fi
                        fi
                        
                        # 更新回答次数
                        local new_count=$(increment_reply_count "$task_idx" "$reply_count_file")
                        echo "📊 任务 $task_idx 的回答次数: $new_count" | tee -a "$main_log_file"
                        
                        # 如果回答次数 > 1，终止任务
                        if [ "$new_count" -gt 1 ]; then
                          echo "⚠️  任务 $task_idx 已自动回答 ${new_count} 次，将跳过此任务" | tee -a "$main_log_file"
                          kill -TERM "$task_pid" 2>/dev/null || true
                          sleep 2
                          kill -KILL "$task_pid" 2>/dev/null || true
                          exit 0
                        fi
                        
                        # 更新日志大小，避免立即再次触发
                        last_log_size=$(stat -f %z "$main_log_file" 2>/dev/null || stat -c %s "$main_log_file" 2>/dev/null || echo 0)
                        last_update_time=$current_time
                        warning_sent=false
                      fi
                    fi
                  fi
                  
                  rm -f "$temp_stdout" "$temp_stderr"
                fi
              fi
            fi
          fi
        fi
      fi
    done
  ) &
  monitor_pid=$!
  
  # 等待任务完成
  wait "$task_pid" 2>/dev/null || true
  
  # 停止监控进程
  kill "$monitor_pid" 2>/dev/null || true
  wait "$monitor_pid" 2>/dev/null || true
  
  # 检查是否因超时终止
  if [ -f "$timeout_flag_file" ]; then
    rm -f "$timeout_flag_file"
    rm -f "$exit_code_file"
    return 124  # 返回超时退出码
  fi
  
  # 读取实际退出码
  local exit_code=1  # 默认失败
  if [ -f "$exit_code_file" ]; then
    exit_code=$(cat "$exit_code_file" 2>/dev/null || echo 1)
    rm -f "$exit_code_file"
  fi
  
  return $exit_code
}

# 读取已执行的任务列表
load_completed_tasks() {
  local state_file="$1"
  local array_name="$2"
  eval "$array_name=()"
  
  if [ -f "$state_file" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      if [[ -n "$line" ]]; then
        eval "$array_name+=(\"$line\")"
      fi
    done < "$state_file"
  fi
  
  # 确保数组已定义（即使为空）
  eval "local count=\${#${array_name}[@]}"
  if [ -z "$count" ]; then
    eval "$array_name=()"
  fi
}

# 保存已执行的任务（避免重复，无论成功或失败）
save_completed_task() {
  local state_file="$1"
  local task_idx="$2"
  
  # 检查任务是否已经存在于状态文件中
  if [ -f "$state_file" ] && grep -q "^${task_idx}$" "$state_file"; then
    return 0  # 已存在，不需要重复添加
  fi
  
  # 追加到状态文件
  echo "$task_idx" >> "$state_file"
}

# 检查任务是否已执行过
is_task_completed() {
  local task_idx="$1"
  local array_name="$2"
  local completed
  local count
  
  # 检查数组是否为空
  eval "count=\${#${array_name}[@]:-0}"
  if [ "$count" -eq 0 ]; then
    return 1  # 数组为空，未执行过
  fi
  
  # 使用 eval 来访问动态变量名（兼容 bash 3.x）
  eval "for completed in \"\${${array_name}[@]}\"; do
    if [[ \"\$completed\" == \"\$task_idx\" ]]; then
      return 0  # 已执行过
    fi
  done"
  return 1  # 未执行过
}

# 创建临时文件目录（如果不存在）
mkdir -p "$TMP_DIR"

echo "开始批量运行任务..." | tee -a "$LOG_FILE"
echo "任务总数: ${#TASKS[@]}" | tee -a "$LOG_FILE"
echo "项目路径: ${PROJECT_PATH}" | tee -a "$LOG_FILE"
echo "超时设置: ${TIMEOUT_SECONDS}秒 (${TIMEOUT_SECONDS}秒无响应将自动跳过)" | tee -a "$LOG_FILE"
echo "停滞监控: 超过 ${STALL_WARNING_SECONDS} 秒无日志更新将尝试自动回答" | tee -a "$LOG_FILE"
echo "Rate Limit 控制: 任务间隔 ${TASK_DELAY_SECONDS} 秒（避免 429 错误）" | tee -a "$LOG_FILE"
echo "回答次数跟踪文件: $REPLY_COUNT_FILE" | tee -a "$LOG_FILE"
echo "临时文件目录: $TMP_DIR" | tee -a "$LOG_FILE"
echo "================================" | tee -a "$LOG_FILE"

# 加载已执行的任务
COMPLETED_TASKS=()
load_completed_tasks "$STATE_FILE" COMPLETED_TASKS

# 安全地检查数组长度（兼容 set -u）
completed_count=${#COMPLETED_TASKS[@]:-0}
if [ "$completed_count" -gt 0 ]; then
  echo "检测到已执行的任务: ${COMPLETED_TASKS[*]}" | tee -a "$LOG_FILE"
  echo "将从断点继续执行（已跳过 ${completed_count} 个已执行的任务）..." | tee -a "$LOG_FILE"
  echo "注意：已执行的任务（无论成功或失败）不会重复执行" | tee -a "$LOG_FILE"
else
  echo "未检测到已执行的任务，将从头开始执行..." | tee -a "$LOG_FILE"
fi

# 计数器
SUCCESS_COUNT=0
FAIL_COUNT=0
TIMEOUT_COUNT=0
SKIP_COUNT=0
SUCCESS_TASKS=()
FAIL_TASKS=()
TIMEOUT_TASKS=()

# 遍历任务列表
for task_idx in "${TASKS[@]}"; do
    # 检查任务是否已执行过
    if is_task_completed "$task_idx" COMPLETED_TASKS; then
        echo "" | tee -a "$LOG_FILE"
        echo "$(date '+%Y-%m-%d %H:%M:%S') - ⏭ 跳过已执行的任务 $task_idx" | tee -a "$LOG_FILE"
        ((SKIP_COUNT++))
        continue
    fi
    
    # 检查任务是否已经回答过多次
    reply_count=$(get_reply_count "$task_idx" "$REPLY_COUNT_FILE")
    if [ "$reply_count" -gt 1 ]; then
        echo "" | tee -a "$LOG_FILE"
        echo "$(date '+%Y-%m-%d %H:%M:%S') - ⏭ 任务 $task_idx 已自动回答 ${reply_count} 次，跳过此任务" | tee -a "$LOG_FILE"
        ((SKIP_COUNT++))
        continue
    fi
    
    echo "" | tee -a "$LOG_FILE"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - 开始执行任务 $task_idx" | tee -a "$LOG_FILE"
    echo "================================" | tee -a "$LOG_FILE"
    
    # 使用超时监控执行任务（临时禁用 set -e 以正确处理退出码）
    set +e
    run_task_with_timeout "$task_idx" "$LOG_FILE" "$PROJECT_PATH" "$TIMEOUT_SECONDS"
    task_exit_code=$?
    set -e
    
    # 根据执行结果分类统计（不重试，直接跳过）
    # 确保 task_exit_code 有值，默认为 1（失败）
    task_exit_code=${task_exit_code:-1}
    
    if [ "$task_exit_code" -eq 0 ]; then
      echo "✓ 任务 $task_idx 执行成功" | tee -a "$LOG_FILE"
      ((SUCCESS_COUNT++))
      SUCCESS_TASKS+=("$task_idx")
    elif [ "$task_exit_code" -eq 124 ]; then
      echo "⚠ 任务 $task_idx 超时（已跳过，不重试）" | tee -a "$LOG_FILE"
      ((TIMEOUT_COUNT++))
      TIMEOUT_TASKS+=("$task_idx")
    else
      echo "✗ 任务 $task_idx 执行失败 (退出码: $task_exit_code，已跳过，不重试)" | tee -a "$LOG_FILE"
      ((FAIL_COUNT++))
      FAIL_TASKS+=("$task_idx")
    fi
    
    # 无论任务成功还是失败，都保存到状态文件，确保不会重复执行
    save_completed_task "$STATE_FILE" "$task_idx"
    COMPLETED_TASKS+=("$task_idx")
    
    echo "================================" | tee -a "$LOG_FILE"
    
    # Rate Limit 控制：任务正常完成后，等待指定时间再执行下一个任务
    # 如果任务超时或失败，也等待一下再继续（避免连续失败导致的问题）
    # 跳过最后一个任务后的延迟（因为后面没有任务了）
    last_task_idx="${TASKS[${#TASKS[@]}-1]}"
    if [ "$task_idx" != "$last_task_idx" ]; then
      echo "$(date '+%Y-%m-%d %H:%M:%S') - ⏸ 等待 ${TASK_DELAY_SECONDS} 秒后继续下一个任务（Rate Limit 控制）..." | tee -a "$LOG_FILE"
      sleep "$TASK_DELAY_SECONDS"
    fi
done

# 输出总结
echo "" | tee -a "$LOG_FILE"
echo "================================" | tee -a "$LOG_FILE"
echo "批量任务执行完成" | tee -a "$LOG_FILE"
echo "成功: $SUCCESS_COUNT" | tee -a "$LOG_FILE"
echo "失败: $FAIL_COUNT" | tee -a "$LOG_FILE"
echo "超时: $TIMEOUT_COUNT" | tee -a "$LOG_FILE"
echo "跳过: $SKIP_COUNT" | tee -a "$LOG_FILE"
echo "总计: ${#TASKS[@]}" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# 列出成功的任务
if [ ${#SUCCESS_TASKS[@]} -gt 0 ]; then
  echo "✓ 成功的任务列表:" | tee -a "$LOG_FILE"
  echo "${SUCCESS_TASKS[*]}" | tee -a "$LOG_FILE"
else
  echo "✓ 成功的任务列表: 无" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"

# 列出失败的任务
if [ ${#FAIL_TASKS[@]} -gt 0 ]; then
  echo "✗ 失败的任务列表:" | tee -a "$LOG_FILE"
  echo "${FAIL_TASKS[*]}" | tee -a "$LOG_FILE"
else
  echo "✗ 失败的任务列表: 无" | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"

# 列出超时的任务
if [ ${#TIMEOUT_TASKS[@]} -gt 0 ]; then
  echo "⚠ 超时的任务列表:" | tee -a "$LOG_FILE"
  echo "${TIMEOUT_TASKS[*]}" | tee -a "$LOG_FILE"
else
  echo "⚠ 超时的任务列表: 无" | tee -a "$LOG_FILE"
fi

echo "================================" | tee -a "$LOG_FILE"
echo "日志文件: $LOG_FILE" | tee -a "$LOG_FILE"
echo "状态文件: $STATE_FILE" | tee -a "$LOG_FILE"
echo "临时文件目录: $TMP_DIR" | tee -a "$LOG_FILE"
echo "================================" | tee -a "$LOG_FILE"

# 清理临时文件目录（可选：保留目录，只清理文件）
# 如果需要完全清理，可以取消下面的注释
# rm -rf "$TMP_DIR" 2>/dev/null || true
