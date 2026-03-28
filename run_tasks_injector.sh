#!/bin/bash

set -euo pipefail

export OPENAI_API_BASE_URL="https://yunwu.ai/v1"

# 配置文件路径
CONFIG_PATH="metagpt/injector/injector_config.yaml"
LLM_CONFIG_PATH="config/config2.yaml"  # 用于自动回答的 LLM 配置
BACKUP_PATH="$(mktemp)"
trap 'cp "$BACKUP_PATH" "$CONFIG_PATH"' EXIT
cp "$CONFIG_PATH" "$BACKUP_PATH"
# 任务列表 - 这些是要执行的HumanEval任务索引
# 生成 0-163 的任务列表，排除: 75, 116, 129, 145
TASKS=()
EXCLUDED_TASKS=(75 116 129 145)
for i in {0..163}; do
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

# 停滞监控设置（秒）
# 如果任务超过此时间没有日志更新，会输出提醒信息
STALL_WARNING_SECONDS=120  # 2分钟无更新则提醒
STALL_CHECK_INTERVAL=30     # 每30秒检查一次
STALL_TIMEOUT_SECONDS=200   # 3分钟无更新则直接跳过任务

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
        # 如果是相对路径，尝试从当前工作目录或脚本所在目录查找
        log_file = os.path.abspath(log_file)
    
    # 检查文件是否存在
    if not os.path.exists(log_file):
        print(f"Error: Log file not found: {log_file}", file=sys.stderr)
        print(f"  Current working directory: {os.getcwd()}", file=sys.stderr)
        sys.exit(1)
    
    # 检查文件是否可读
    if not os.access(log_file, os.R_OK):
        print(f"Error: Log file is not readable: {log_file}", file=sys.stderr)
        sys.exit(1)
    
    with open(log_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        content = ''.join(lines)
    
    if not lines:
        print(f"Error: Log file is empty: {log_file}", file=sys.stderr)
        sys.exit(1)
    
    # 提取 [REQUIREMENT] 部分（从 [REQUIREMENT] 开始到连续两个空行或新日志条目）
    requirement = ""
    in_requirement = False
    requirement_lines = []
    consecutive_empty = 0
    
    for i, line in enumerate(lines):
        if '[REQUIREMENT]' in line:
            in_requirement = True
            consecutive_empty = 0
            # 提取这一行中 [REQUIREMENT] 之后的内容
            req_start = line.find('[REQUIREMENT]') + len('[REQUIREMENT]')
            remaining = line[req_start:].strip()
            if remaining:
                requirement_lines.append(remaining)
            continue
        
        if in_requirement:
            # 检查是否是新的日志条目开始（时间戳格式：YYYY-MM-DD）
            if re.match(r'^\d{4}-\d{2}-\d{2}', line.strip()):
                break
            
            # 检查连续空行（两个空行表示结束）
            if not line.strip():
                consecutive_empty += 1
                if consecutive_empty >= 2 and requirement_lines:
                    # 检查下一行是否是新的日志条目
                    if i + 1 < len(lines) and re.match(r'^\d{4}-\d{2}-\d{2}', lines[i + 1].strip()):
                        break
                # 即使有空行也保留，因为可能是格式的一部分
                requirement_lines.append("")
            else:
                consecutive_empty = 0
                requirement_lines.append(line.rstrip())
    
    requirement = '\n'.join(requirement_lines).strip()
    
    # 提取最后一个 RoleZero.ask_human 的问题
    question = ""
    
    # 查找所有包含 RoleZero.ask_human 的位置
    ask_human_positions = []
    for i, line in enumerate(lines):
        if 'RoleZero.ask_human' in line or "RoleZero.ask_human" in line:
            ask_human_positions.append(i)
    
    if ask_human_positions:
        # 从最后一个位置开始提取
        start_idx = ask_human_positions[-1]
        
        # 从这一行开始，查找 'question': ' 之后的内容
        search_text = '\n'.join(lines[start_idx:min(start_idx + 50, len(lines))])
        
        # 匹配 'question': '...' 格式，支持多行内容（使用非贪婪匹配）
        # 注意：question内容可能包含 \n（转义的换行符）
        pattern = r"'question':\s*'((?:[^'\\]|\\.|''|\\n)*?)'\s*[,\}]"
        match = re.search(pattern, search_text, re.DOTALL)
        
        if match:
            question = match.group(1)
            # 处理转义字符
            # 将 \\n 转换为真正的换行符
            question = question.replace("\\n", "\n")
            # 处理其他转义
            question = question.replace("''", "'")  # Python中的 '' 表示单引号
            question = question.replace("\\'", "'")  # 转义的单引号
            question = question.replace("\\\\", "\\")  # 转义的反斜杠
            # 移除末尾可能的转义字符
            question = question.rstrip("\\")
    
    
    # 检查是否有足够的信息生成回答
    if not requirement and not question:
        print("Error: No requirement or question found in log file", file=sys.stderr)
        print(f"  - Requirement found: {bool(requirement)}", file=sys.stderr)
        print(f"  - Question found: {bool(question)}", file=sys.stderr)
        print(f"  - Log file: {log_file}", file=sys.stderr)
        print(f"  - Task index: {task_idx}", file=sys.stderr)
        print(f"  - Log file size: {len(lines)} lines", file=sys.stderr)
        
        # 检查是否有 [REQUIREMENT] 标记
        has_requirement_marker = any('[REQUIREMENT]' in line for line in lines)
        print(f"  - Has [REQUIREMENT] marker: {has_requirement_marker}", file=sys.stderr)
        
        # 检查是否有 ask_human
        has_ask_human = any('RoleZero.ask_human' in line for line in lines)
        print(f"  - Has RoleZero.ask_human: {has_ask_human}", file=sys.stderr)
        
        # 如果找到了标记但提取失败，显示一些上下文
        if has_requirement_marker and not requirement:
            print("  - Warning: Found [REQUIREMENT] marker but extraction failed", file=sys.stderr)
            for i, line in enumerate(lines):
                if '[REQUIREMENT]' in line:
                    print(f"    Line {i+1}: {line[:100]}...", file=sys.stderr)
                    break
        
        if has_ask_human and not question:
            print("  - Warning: Found RoleZero.ask_human but extraction failed", file=sys.stderr)
            for i, line in enumerate(lines):
                if 'RoleZero.ask_human' in line:
                    print(f"    Line {i+1}: {line[:200]}...", file=sys.stderr)
                    break
        
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
    
    # 检查openai模块
    try:
        from openai import OpenAI
    except ImportError as e:
        print(f"Error: openai module not found. Install with: pip install openai", file=sys.stderr)
        print(f"  Import error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # 调用API
    try:
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
        
        # 检查响应
        if not response:
            print("Error: Empty response from API", file=sys.stderr)
            sys.exit(1)
        
        if not response.choices or len(response.choices) == 0:
            print("Error: No choices in API response", file=sys.stderr)
            print(f"  Response object: {response}", file=sys.stderr)
            sys.exit(1)
        
        if not response.choices[0].message or not response.choices[0].message.content:
            print("Error: No content in API response message", file=sys.stderr)
            print(f"  Response choices[0]: {response.choices[0] if response.choices else 'None'}", file=sys.stderr)
            sys.exit(1)
        
        answer = response.choices[0].message.content.strip()
        
        if not answer:
            print("Error: Answer is empty after processing", file=sys.stderr)
            sys.exit(1)
        
        # 确保回答只有一行
        answer = answer.split('\n')[0].strip()
        
        if not answer:
            print("Error: Answer is empty after splitting", file=sys.stderr)
            sys.exit(1)
        
        # 输出回答（会被脚本捕获）
        # 确保输出单独一行，并且最后有一个换行符，这样终端才能正确识别输出完成
        # print() 默认会在末尾添加换行符，但为了确保，我们明确添加
        sys.stdout.write(answer + '\n')
        sys.stdout.flush()  # 确保输出被刷新
        sys.exit(0)
        
    except Exception as api_error:
        print(f"Error: API call failed", file=sys.stderr)
        print(f"  Error type: {type(api_error).__name__}", file=sys.stderr)
        print(f"  Error message: {str(api_error)}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print(f"Error generating reply: {e}", file=sys.stderr)
    print(f"  Error type: {type(e).__name__}", file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
PYTHON_SCRIPT
}

# 回答次数跟踪文件路径（每个规则一个文件）
get_reply_count_file() {
  local rule_id="$1"
  local sanitized_rule="${rule_id//[^A-Za-z0-9_-]/-}"
  echo "/tmp/task_reply_count_${sanitized_rule}.txt"
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
  
  # 创建或更新计数文件
  if [ -f "$count_file" ]; then
    # 如果任务ID已存在，更新计数
    if grep -q "^${task_idx}:" "$count_file" 2>/dev/null; then
      sed -i.bak "s/^${task_idx}:.*/${task_idx}:${new_count}/" "$count_file" 2>/dev/null || \
      sed -i '' "s/^${task_idx}:.*/${task_idx}:${new_count}/" "$count_file" 2>/dev/null
      rm -f "${count_file}.bak" 2>/dev/null
    else
      # 如果任务ID不存在，追加
      echo "${task_idx}:${new_count}" >> "$count_file"
    fi
  else
    # 文件不存在，创建新文件
    echo "${task_idx}:${new_count}" > "$count_file"
  fi
  
  echo "$new_count"
}

# 监控任务停滞并提醒用户
monitor_task_stall() {
  local task_idx="$1"
  local log_file="$2"
  local warning_seconds="$3"
  local check_interval="$4"
  local reply_count_file="$5"  # 新增参数：回答次数跟踪文件
  
  local last_log_size=0
  local last_update_time=$(date +%s)
  local warning_sent=false
  
  # 获取初始日志文件大小
  if [ -f "$log_file" ]; then
    last_log_size=$(stat -f %z "$log_file" 2>/dev/null || stat -c %s "$log_file" 2>/dev/null || echo 0)
  fi
  
  while true; do
    sleep "$check_interval"
    
    # 检查任务进程是否还在运行
    # 使用更精确的匹配，避免误判
    if ! pgrep -f "python.*main\.py.*$task_idx.*--project-path" > /dev/null 2>&1; then
      # 任务已结束，退出监控
      break
    fi
    
    # 检查日志文件是否有更新
    local current_log_size=0
    if [ -f "$log_file" ]; then
      current_log_size=$(stat -f %z "$log_file" 2>/dev/null || stat -c %s "$log_file" 2>/dev/null || echo 0)
    fi
    
    local current_time=$(date +%s)
    local time_since_update=$((current_time - last_update_time))
    
    # 检查是否超过超时阈值（3分钟）
    if [ "$time_since_update" -ge "$STALL_TIMEOUT_SECONDS" ]; then
      # 超过3分钟，直接终止任务并跳过
      local timeout_minutes=$((STALL_TIMEOUT_SECONDS / 60))
      local timeout_message="⏰ 任务 $task_idx 已停滞超过 ${timeout_minutes} 分钟，自动跳过"
      
      echo "" | tee -a "$log_file"
      echo "========================================" | tee -a "$log_file"
      echo "$timeout_message" | tee -a "$log_file"
      echo "当前时间: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$log_file"
      echo "========================================" | tee -a "$log_file"
      echo "" | tee -a "$log_file"
      
      # 查找并终止主进程
      local main_pid=$(pgrep -f "python.*main\.py.*$task_idx.*--project-path" | head -n 1)
      if [ -n "$main_pid" ]; then
        echo "🛑 正在终止任务进程 (PID: $main_pid)..." | tee -a "$log_file"
        kill -TERM "$main_pid" 2>/dev/null || true
        sleep 2
        # 如果进程还在运行，强制终止
        if pgrep -f "python.*main\.py.*$task_idx.*--project-path" > /dev/null 2>&1; then
          kill -KILL "$main_pid" 2>/dev/null || true
          echo "🛑 已强制终止任务进程" | tee -a "$log_file"
        else
          echo "✓ 任务进程已终止" | tee -a "$log_file"
        fi
      else
        echo "⚠️  未找到任务进程，可能已自行退出" | tee -a "$log_file"
      fi
      
      # 退出监控循环
      break
    elif [ "$current_log_size" -gt "$last_log_size" ]; then
      # 日志有更新，重置计时
      last_log_size=$current_log_size
      last_update_time=$current_time
      warning_sent=false
    elif [ "$time_since_update" -ge "$warning_seconds" ] && [ "$warning_sent" = false ]; then
      # 超过阈值且未发送过提醒，输出醒目的提醒信息
      local minutes=$((time_since_update / 60))
      local seconds=$((time_since_update % 60))
      local message="任务 $task_idx 已停滞 ${minutes} 分 ${seconds} 秒，请检查！"
      
      # 尝试自动生成回答
      local auto_reply=""
      local error_output=""
      if command -v python3 > /dev/null 2>&1; then
        echo "🤖 尝试自动生成回答..." >&2
        
        # 查找正确的任务日志文件
        # 日志文件在 /Users/ximenajia/CODE/Tester/MetaGPT/humaneval_baseline/logs/ 目录下
        # 文件名格式: {task_idx}_*.log
        local task_log_dir="/Users/ximenajia/CODE/Tester/MetaGPT/humaneval_baseline/logs"
        local task_log_file=""
        
        if [ -d "$task_log_dir" ]; then
          # 查找匹配的日志文件
          task_log_file=$(find "$task_log_dir" -maxdepth 1 -name "${task_idx}_*.log" -type f | head -n 1)
        fi
        
        if [ -z "$task_log_file" ] || [ ! -f "$task_log_file" ]; then
          echo "⚠️  未找到任务日志文件: ${task_log_dir}/${task_idx}_*.log" >&2
          echo "   使用主日志文件: $log_file" >&2
          task_log_file="$log_file"
        else
          echo "📄 使用任务日志文件: $task_log_file" >&2
        fi
        
        # 分别捕获stdout和stderr
        local temp_stdout=$(mktemp)
        local temp_stderr=$(mktemp)
        local cleanup_temp=1
        
        local exit_code=0
        generate_auto_reply "$task_log_file" "$task_idx" > "$temp_stdout" 2> "$temp_stderr" || exit_code=$?
        
        if [ $exit_code -eq 0 ]; then
          # 成功：读取stdout作为回答
          auto_reply=$(cat "$temp_stdout" 2>/dev/null | tail -n 1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
          error_output=$(cat "$temp_stderr" 2>/dev/null)
          
          # 调试信息
          if [ -n "$error_output" ]; then
            echo "⚠️  警告：API调用成功但有stderr输出" >&2
            echo "stderr: $error_output" >&2
          fi
          
          # 清理临时文件
          rm -f "$temp_stdout" "$temp_stderr"
          cleanup_temp=0
          
          if [ -n "$auto_reply" ] && [ ${#auto_reply} -gt 0 ]; then
            # 验证回答不是错误信息
            if ! echo "$auto_reply" | grep -qiE "(error|traceback|exception|failed|missing|not found)"; then
              # 将回答写入日志文件（使用特殊标记，方便识别）
              {
                echo ""
                echo "[AUTO_REPLY] $(date '+%Y-%m-%d %H:%M:%S')"
                echo "$auto_reply"
                echo "[END_AUTO_REPLY]"
                echo ""
              } >> "$log_file"
              
              # 尝试找到主进程并向其 stdin 发送回答
              # 查找正在运行的主进程（python main.py）
              local main_pid=$(pgrep -f "python.*main\.py.*$task_idx.*--project-path" | head -n 1)
              
              # 如果在 tmux 中，尝试使用 tmux send-keys 发送回答
              if [ -n "${TMUX:-}" ] && [ -n "$main_pid" ]; then
                # 获取当前 tmux 窗格（如果未设置，尝试找到包含主进程的窗格）
                local tmux_target="${TMUX_PANE:-}"
                if [ -z "$tmux_target" ]; then
                  # 尝试找到包含主进程的窗格
                  tmux_target=$(tmux list-panes -a -F "#{pane_id} #{pane_pid}" 2>/dev/null | grep " $main_pid$" | cut -d' ' -f1 | head -n 1)
                fi
                
                if [ -n "$tmux_target" ]; then
                  # 转义特殊字符并发送
                  local escaped_reply=$(echo "$auto_reply" | sed "s/'/'\\\\''/g")
                  tmux send-keys -t "$tmux_target" "$escaped_reply" Enter 2>/dev/null && {
                    echo "📤 已通过 tmux 向主进程发送回答 (PID: $main_pid, 窗格: $tmux_target)" >&2
                  } || {
                    echo "⚠️  tmux send-keys 失败" >&2
                  }
                else
                  echo "⚠️  未找到对应的 tmux 窗格" >&2
                fi
              elif [ -n "$main_pid" ]; then
                # 不在 tmux 中，尝试其他方法（Linux /proc 或 macOS lsof）
                if [ -d "/proc" ]; then
                  # Linux: 尝试通过 /proc 发送
                  echo "$auto_reply" > "/proc/$main_pid/fd/0" 2>/dev/null && {
                    echo "📤 已通过 /proc 向主进程发送回答 (PID: $main_pid)" >&2
                  } || {
                    echo "⚠️  无法通过 /proc 发送回答" >&2
                  }
                else
                  # macOS: 提示需要手动输入
                  echo "⚠️  在 macOS 非 tmux 环境中，无法自动发送回答" >&2
                  echo "   请手动在终端中输入: $auto_reply" >&2
                fi
              else
                echo "⚠️  未找到主进程 PID" >&2
              fi
              
              # 记录回答次数（如果提供了跟踪文件）
              if [ -n "$reply_count_file" ]; then
                local new_count=$(increment_reply_count "$task_idx" "$reply_count_file")
                echo "📊 任务 $task_idx 的回答次数: $new_count" >&2
                
                # 如果回答次数 > 1，记录到日志并准备跳过任务
                if [ "$new_count" -gt 1 ]; then
                  echo "" | tee -a "$log_file"
                  echo "⚠️  任务 $task_idx 已自动回答 ${new_count} 次，将跳过此任务" | tee -a "$log_file"
                  echo "当前时间: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$log_file"
                  echo "" | tee -a "$log_file"
                  
                  # 终止主进程
                  local main_pid=$(pgrep -f "python.*main\.py.*$task_idx.*--project-path" | head -n 1)
                  if [ -n "$main_pid" ]; then
                    echo "🛑 正在终止任务进程 (PID: $main_pid)..." | tee -a "$log_file"
                    kill -TERM "$main_pid" 2>/dev/null || true
                    sleep 2
                    if pgrep -f "python.*main\.py.*$task_idx.*--project-path" > /dev/null 2>&1; then
                      kill -KILL "$main_pid" 2>/dev/null || true
                    fi
                  fi
                  
                  # 退出监控循环
                  break
                fi
              fi
              
              # 更新日志大小，避免立即再次触发
              if [ -f "$log_file" ]; then
                last_log_size=$(stat -f %z "$log_file" 2>/dev/null || stat -c %s "$log_file" 2>/dev/null || echo 0)
                last_update_time=$(date +%s)
              fi
              
              # 输出到终端
              echo -e "\n\033[1;32m🤖 自动回答已生成:\033[0m" >&2
              echo -e "\033[1;33m$auto_reply\033[0m" >&2
              echo "" >&2
            else
              echo "⚠️  自动回答格式错误（包含错误关键词）" >&2
              echo "回答内容: $auto_reply" >&2
            fi
          else
            echo "⚠️  自动回答为空" >&2
            if [ -n "$error_output" ]; then
              echo "错误信息: $error_output" >&2
            fi
          fi
        else
          # 失败：读取stderr作为错误信息
          error_output=$(cat "$temp_stderr" 2>/dev/null || echo "未知错误")
          auto_reply=$(cat "$temp_stdout" 2>/dev/null || echo "")
          
          # 清理临时文件
          rm -f "$temp_stdout" "$temp_stderr"
          cleanup_temp=0
          
          echo "⚠️  自动回答生成失败 (退出码: $exit_code)" >&2
          if [ -n "$error_output" ]; then
            echo "错误信息:" >&2
            echo "$error_output" | head -10 >&2  # 只显示前10行，避免输出过长
          else
            echo "未捕获到错误信息" >&2
          fi
          if [ -n "$auto_reply" ]; then
            echo "标准输出: $auto_reply" >&2
          fi
        fi
      else
        echo "⚠️  无法生成自动回答（需要 python3）" >&2
      fi
      
      # 1. 终端高亮显示（使用 ANSI 颜色代码）- 只输出到终端
      echo -e "\n\033[1;31m" >&2  # 红色粗体，输出到 stderr 避免被 tee 捕获
      echo "========================================" >&2
      echo "⚠️  ⚠️  ⚠️  任务停滞提醒 ⚠️  ⚠️  ⚠️" >&2
      echo "========================================" >&2
      echo -e "\033[0m" >&2  # 重置颜色
      echo "$message" >&2
      echo "当前时间: $(date '+%Y-%m-%d %H:%M:%S')" >&2
      echo "请检查任务是否卡住，或考虑手动干预" >&2
      echo -e "\033[1;31m========================================\033[0m" >&2
      echo "" >&2
      
      # 2. 终端响铃（发出声音）
      echo -e "\a\a\a" >&2  # 三次响铃
      
      # 3. macOS 系统通知
      if command -v osascript > /dev/null 2>&1; then
        osascript -e "display notification \"任务 $task_idx 已停滞 ${minutes} 分 ${seconds} 秒，请检查！\" with title \"任务停滞提醒\" sound name \"Basso\"" 2>/dev/null || true
      fi
      
      # 4. 语音提醒（macOS say 命令）
      if command -v say > /dev/null 2>&1; then
        say "警告，任务 $task_idx 已停滞，请检查" 2>/dev/null &
      fi
      
      # 5. 写入日志文件（避免重复）
      echo "" | tee -a "$log_file"
      echo "========================================" | tee -a "$log_file"
      echo "⚠️  ⚠️  ⚠️  任务停滞提醒 ⚠️  ⚠️  ⚠️" | tee -a "$log_file"
      echo "========================================" | tee -a "$log_file"
      echo "$message" | tee -a "$log_file"
      echo "当前时间: $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "$log_file"
      echo "请检查任务是否卡住，或考虑手动干预" | tee -a "$log_file"
      echo "========================================" | tee -a "$log_file"
      echo "" | tee -a "$log_file"
      
      warning_sent=true
    fi
  done
}

# 启用/禁用全局配置
enable_global_config() {
  local enabled_flag="${1:-true}"  # 默认为 true
  python - "$CONFIG_PATH" "$enabled_flag" <<'PY'
from pathlib import Path
import sys
import yaml

config_path = Path(sys.argv[1])
enabled_flag = sys.argv[2].lower() == "true"
data = yaml.safe_load(config_path.read_text())

# 设置全局配置
data["enabled"] = enabled_flag

config_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False))
PY
}


# 故障注入规则列表
RULE_IDS=()
EXTRA_ARGS=()
while (($#)); do
  if [[ "$1" == "--" ]]; then
    shift
    EXTRA_ARGS=("$@")
    break
  fi
  RULE_IDS+=("$1")
  shift
done

if [ ${#RULE_IDS[@]} -eq 0 ]; then
  RULE_IDS=(
    # wrong_tool_selection

    # message_duplication_storm
    # broadcast_amplification
    # echo_loop_injection

    # weak_parameter_filling
    # tool_format_error

    # info_loss_critical

    # 有一些反问的情况
    # logic_conflict
    # goal_unclear
    reasoning_anomaly_injection
    # unexecutable_plan_generation
    # memory_loss_injection
    # info_loss_critical
    # long_context_injection
    # role_mix
  )
fi

# 映射 rule_id 到配置文件的 section
map_rule_to_section() {
  local rule_id="$1"
  case "$rule_id" in
    long_context_injection|reasoning_anomaly_injection|info_loss_critical|unexecutable_plan_generation|memory_loss_injection)
      echo "llm_injection"
      ;;
    goal_unclear|logic_conflict)
      echo "input_prompt_faults"
      ;;
    wrong_tool_selection|weak_parameter_filling|tool_format_error)
      echo "tool_calling_faults"
      ;;
    message_duplication_storm|broadcast_amplification|echo_loop_injection)
      echo "communication_faults"
      ;;
    *)
      echo ""  # Unknown
      ;;
  esac
}

# 设置配置文件中指定 section 的状态
set_section_state() {
  local section="$1"
  local rule_id="$2"
  local enabled_flag="$3"
  python - "$CONFIG_PATH" "$section" "$rule_id" "$enabled_flag" <<'PY'
import sys
from pathlib import Path
import yaml

config_path = Path(sys.argv[1])
section = sys.argv[2]
rule_id = sys.argv[3]
enabled_flag = sys.argv[4].lower() == "true"

data = yaml.safe_load(config_path.read_text())

sections = ("llm_injection", "input_prompt_faults", "tool_calling_faults", "communication_faults")
for name in sections:
    sec = data.get(name)
    if not isinstance(sec, dict):
        continue
    if name == section:
        sec["enabled"] = enabled_flag
        if rule_id:
            sec["rule_id"] = rule_id
        # 处理 target_receiver：只有 memory_loss_injection 规则时设置为 "Alex"，其他情况设置为 None
        if name == "llm_injection":
            if rule_id == "reasoning_anomaly_injection":
                sec["target_receiver"] = "Alex"
            else:
                sec["target_receiver"] = None
    else:
        sec["enabled"] = False

config_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False))
PY
}

# 禁用所有 section
disable_all_sections() {
  python - "$CONFIG_PATH" <<'PY'
from pathlib import Path
import sys
import yaml

config_path = Path(sys.argv[1])
data = yaml.safe_load(config_path.read_text())

for name in ("llm_injection", "input_prompt_faults", "tool_calling_faults", "communication_faults"):
    sec = data.get(name)
    if isinstance(sec, dict):
        sec["enabled"] = False
        # 如果是 llm_injection，重置 target_receiver
        if name == "llm_injection":
            sec["target_receiver"] = None

config_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False))
PY
}

# 遍历每个故障注入规则
for rule_id in "${RULE_IDS[@]}"; do
  
  echo "" >&2
  echo "========================================" >&2
  echo "=== 使用故障注入规则: ${rule_id}" >&2
  echo "========================================" >&2
  
  # 如果 rule_id 是 role_mix，禁用全局配置；否则启用全局配置
  if [[ "$rule_id" == "role_mix" ]]; then
    echo "检测到 role_mix，禁用全局配置" >&2
    enable_global_config false
    # role_mix 不需要设置 section，直接跳过 section 相关处理
    section=""
  else
    enable_global_config true
    section="$(map_rule_to_section "$rule_id")"
    if [[ -z "$section" ]]; then
      echo "跳过未知的 rule_id: $rule_id" >&2
      continue
    fi
    # 启用当前规则
    set_section_state "$section" "$rule_id" true
  fi
  
  # 清理 rule_id 用于目录名
  sanitized_rule="$rule_id"
  sanitized_rule="${sanitized_rule//[^A-Za-z0-9_-]/-}"
  
  # 固定的项目路径
  PROJECT_PATH="/Users/ximenajia/CODE/Tester/MetaGPT/humaneval_baseline"
  
  # 日志文件
  LOG_FILE="./run_tasks_${sanitized_rule}_$(date +%Y%m%d_%H%M%S).log"
  
  echo "开始批量运行任务 (规则: ${rule_id})..." | tee -a "$LOG_FILE"
  echo "任务总数: ${#TASKS[@]}" | tee -a "$LOG_FILE"
  echo "项目路径: ${PROJECT_PATH}" | tee -a "$LOG_FILE"
  echo "停滞监控: 超过 ${STALL_WARNING_SECONDS} 秒无日志更新将提醒" | tee -a "$LOG_FILE"
  echo "超时设置: 超过 ${STALL_TIMEOUT_SECONDS} 秒（$((STALL_TIMEOUT_SECONDS / 60)) 分钟）无日志更新将自动跳过任务" | tee -a "$LOG_FILE"
  echo "================================" | tee -a "$LOG_FILE"
  
  # 计数器和任务列表
  SUCCESS_COUNT=0
  FAIL_COUNT=0
  SKIP_COUNT=0
  SUCCESS_TASKS=()
  FAIL_TASKS=()
  SKIP_TASKS=()
  
  # 创建回答次数跟踪文件
  REPLY_COUNT_FILE=$(get_reply_count_file "$rule_id")
  echo "回答次数跟踪文件: $REPLY_COUNT_FILE" | tee -a "$LOG_FILE"
  
  # 遍历任务列表
  for task_idx in "${TASKS[@]}"; do
      echo "" | tee -a "$LOG_FILE"
      echo "$(date '+%Y-%m-%d %H:%M:%S') - 开始执行任务 $task_idx" | tee -a "$LOG_FILE"
      echo "================================" | tee -a "$LOG_FILE"
      
      # 检查任务是否已经回答过多次
      reply_count=$(get_reply_count "$task_idx" "$REPLY_COUNT_FILE")
      if [ "$reply_count" -gt 1 ]; then
          echo "⏭️  任务 $task_idx 已自动回答 ${reply_count} 次，跳过此任务" | tee -a "$LOG_FILE"
          echo "================================" | tee -a "$LOG_FILE"
          ((SKIP_COUNT++))
          SKIP_TASKS+=("$task_idx")
          continue
      fi
      
      # 启动停滞监控（后台运行）
      monitor_task_stall "$task_idx" "$LOG_FILE" "$STALL_WARNING_SECONDS" "$STALL_CHECK_INTERVAL" "$REPLY_COUNT_FILE" &
      monitor_pid=$!
      
      # 调用 main.py
      # 使用 PIPESTATUS 获取 python 的退出码，而不是 tee 的退出码
      set +o pipefail  # 临时禁用 pipefail，以便正确捕获退出码
      python main.py "$task_idx" --project-path "$PROJECT_PATH" 2>&1 | tee -a "$LOG_FILE"
      task_exit_code=${PIPESTATUS[0]}
      set -o pipefail  # 恢复 pipefail
      
      # 停止监控进程
      kill "$monitor_pid" 2>/dev/null || true
      wait "$monitor_pid" 2>/dev/null || true
      
      # 检查执行结果
      # 确保 task_exit_code 有值，默认为 1（失败）
      task_exit_code=${task_exit_code:-1}
      
      if [ "$task_exit_code" -eq 0 ]; then
          echo "✓ 任务 $task_idx 执行成功" | tee -a "$LOG_FILE"
          ((SUCCESS_COUNT++))
          SUCCESS_TASKS+=("$task_idx")
      else
          echo "✗ 任务 $task_idx 执行失败" | tee -a "$LOG_FILE"
          ((FAIL_COUNT++))
          FAIL_TASKS+=("$task_idx")
      fi
      
      echo "================================" | tee -a "$LOG_FILE"
      
      # 任务结束后等待5秒（跳过最后一个任务）
      last_task_idx="${TASKS[${#TASKS[@]}-1]}"
      if [ "$task_idx" != "$last_task_idx" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - ⏸ 等待 5 秒后继续下一个任务..." | tee -a "$LOG_FILE"
        sleep 5
      fi
  done
  
  # 输出总结
  echo "" | tee -a "$LOG_FILE"
  echo "================================" | tee -a "$LOG_FILE"
  echo "批量任务执行完成 (规则: ${rule_id})" | tee -a "$LOG_FILE"
  echo "成功: $SUCCESS_COUNT" | tee -a "$LOG_FILE"
  echo "失败: $FAIL_COUNT" | tee -a "$LOG_FILE"
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
  
  # 列出跳过的任务
  if [ ${#SKIP_TASKS[@]} -gt 0 ]; then
    echo "⏭️  跳过的任务列表 (回答次数 > 1):" | tee -a "$LOG_FILE"
    echo "${SKIP_TASKS[*]}" | tee -a "$LOG_FILE"
  else
    echo "⏭️  跳过的任务列表: 无" | tee -a "$LOG_FILE"
  fi
  
  echo "================================" | tee -a "$LOG_FILE"
  echo "日志文件: $LOG_FILE" | tee -a "$LOG_FILE"
  echo "================================" | tee -a "$LOG_FILE"
  
  # 重命名项目目录
  TARGET_PATH="./humaneval_baseline_${sanitized_rule}_$(date +%Y%m%d_%H%M%S)"
  if [ -d "$PROJECT_PATH" ]; then
    echo "" | tee -a "$LOG_FILE"
    echo "重命名项目目录: $PROJECT_PATH -> $TARGET_PATH" | tee -a "$LOG_FILE"
    # 如果目标目录已存在，先删除
    if [ -d "$TARGET_PATH" ]; then
      rm -rf "$TARGET_PATH"
      echo "已删除旧的目标目录: $TARGET_PATH" | tee -a "$LOG_FILE"
    fi
    mv "$PROJECT_PATH" "$TARGET_PATH"
    echo "✓ 项目目录重命名完成" | tee -a "$LOG_FILE"
  else
    echo "⚠ 警告: 项目目录不存在: $PROJECT_PATH" | tee -a "$LOG_FILE"
  fi
  
  # 禁用所有规则
  disable_all_sections
done

echo "" >&2
echo "========================================" >&2
echo "=== 所有故障注入规则执行完成" >&2
echo "========================================" >&2