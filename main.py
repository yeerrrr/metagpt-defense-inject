import argparse
import asyncio
import json  
import os
import sys
from pathlib import Path  
from metagpt.software_company import generate_repo  
from metagpt.ext.aflow.benchmark.humaneval import HumanEvalBenchmark
from metagpt.logs import logger as _logger

# 将 human-eval 目录添加到 Python 路径
sys.path.append(str(Path(__file__).parent.parent / "human-eval"))
# from select_humaneval_tasks import select_tasks_by_difficulty # type: ignore

# Ensure an event loop exists before MetaGPT roles create asyncio primitives
# asyncio.set_event_loop(asyncio.new_event_loop())

def ensure_event_loop():
    """
    Ensure there's an asyncio event loop set for the current thread.
    Some MetaGPT components (Pydantic factories / role setup) create
    asyncio primitives during construction and require a loop to exist.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

# Create a loop at import time to avoid "no current event loop" errors
ensure_event_loop()

def setup_task_logger(entry_point: str, log_dir: Path):
    """
    为每个任务设置独立的日志文件
    
    Args:
        entry_point: 任务入口点名称（用作日志文件名）
        log_dir: 日志目录路径
    """
    # 确保日志目录存在
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # 日志文件路径
    log_file = log_dir / f"{entry_point}.log"
    
    # 移除现有的文件日志处理器（保留控制台输出）
    _logger.remove()
    
    # 重新添加控制台输出（INFO级别）
    _logger.add(sys.stderr, level="INFO")
    
    # 添加文件日志（DEBUG级别，使用任务名作为文件名）
    _logger.add(
        log_file,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",  # 当日志文件超过10MB时轮转
        retention="7 days"  # 保留7天的日志
    )
    
    _logger.info(f"日志已配置: {log_file}")
    return _logger
  
  
def run_humaneval_with_metagpt(task_idx, task, project_path):  
    """
    运行 HumanEval 任务
    
    Args:
        task: HumanEval 任务字典
        project_path: 项目路径
        humaneval_path: HumanEval JSONL 文件路径
        log_dir: 日志目录（如果为None，使用 project_path/logs）
    """
    # 确保事件循环存在（在每个任务开始前）
    ensure_event_loop()

    # 设置任务日志目录
    log_dir = Path(project_path) / "logs"
    setup_task_logger(f"{task_idx}_{task['entry_point']}", log_dir)
    print(f"project_path: {Path(project_path).resolve()}")
    requirement = f"""Write a Python function: {task['prompt']} 
        IMPORTANT REQUIREMENTS:  
        1. Save the code to a file named '{task['entry_point']}.py'  
        2. The file must be saved in the project directory: "{project_path}"  
        3. The file should contain ONLY the function implementation with proper imports  
        4. Ensure the file is written to disk before completing the task  
        
        """ 
    
    _logger.info(f"[BEGINNING OF TASK] {task['task_id']} - {task['entry_point']}")
    _logger.debug(f"[REQUIREMENT] {requirement}")
    print(f"需求: {requirement}")
      
    # 使用 generate_repo - 这就是命令行工具内部使用的函数 
    # 打印实际项目路径
    print(f"指定项目路径: {Path(project_path).resolve()}")
    generate_repo(  
        idea=requirement,  
        investment=3.0,  
        n_round=5,  
        code_review=False,  
        run_tests=False,  
        implement=True,  
        project_name="humaneval_test",  
        inc=False,  
        project_path=project_path,  
        reqa_file="",  
        max_auto_summarize_code=0,  
        recover_path=None  
    )
      
    if not Path(project_path).exists():  
        raise Exception(f"错误: 项目路径不存在: {project_path}")
      
    # 列出项目文件结构  
    print("\n项目文件结构:")  
    for file in Path(project_path).rglob("*"):  
        if file.is_file():  
            print(f"  {file.relative_to(project_path)}")  
      
    # 初始化评测器  
    eval_log_path = Path(project_path) / "eval_logs"  
    eval_log_path.mkdir(parents=True, exist_ok=True)  
      
    benchmark = HumanEvalBenchmark(  
        name="HumanEval",  
        file_path=humaneval_path,  
        log_path=str(eval_log_path)  
    )  
      
    # 搜索生成的代码  
    possible_paths = [  
        Path(project_path) / f"{task['entry_point']}.py",  
    ]  
    
    generated_code = None  
    found_path = None  
      
    for code_path in possible_paths:  
        if code_path.exists():  
            with open(code_path, 'r', encoding='utf-8') as f:  
                generated_code = f.read()  
            found_path = code_path  
            print(f"\n✓ 找到代码文件: {code_path}")  
            break  
      
    if not generated_code:  
        print(f"\n递归搜索所有Python文件...")  
        for py_file in Path(project_path).rglob("*.py"):  
            try:  
                with open(py_file, 'r', encoding='utf-8') as f:  
                    content = f.read()  
                    if f"def {task['entry_point']}" in content:  
                        generated_code = content  
                        found_path = py_file  
                        print(f"✓ 在 {py_file.relative_to(project_path)} 中找到函数")  
                        break  
            except Exception:  
                continue  
      
    # 评测代码  
    if generated_code:  
        print(f"\n{'='*60}")  
        print(f"开始评测")  
        print(f"{'='*60}")  
        print(f"任务ID: {task['task_id']}")  
        print(f"函数名: {task['entry_point']}")  
        _logger.info(f"[BEGINNING OF EVALUATION] {task['task_id']} - {task['entry_point']}")
          
        result = benchmark.check_solution(  
            solution=generated_code,  
            test=task['test'],  
            entry_point=task['entry_point']  
        )  
          
        is_pass = result[0] == benchmark.PASS
        
        print(f"\n{'='*60}")
        print(f"评测结果: {'✓ 通过' if is_pass else '✗ 失败'}")  
        print(f"{'='*60}")
        print(f"\n详细信息:\n{result[1]}")  

        _logger.info(f"[EVALUATION RESULT] {'PASS' if is_pass else 'FAIL'}")
        _logger.debug(f"[EVALUATION DETAIL] {result[1]}")
          
        # 保存结果  
        # 使用 task_idx 和 entry_point 来避免同名函数覆盖（如 triangle_area 在索引45和71都存在）
        result_file = eval_log_path / f"{task_idx}_evaluation_result_{task['entry_point']}.txt"  
        with open(result_file, 'w', encoding='utf-8') as f:  
            f.write(f"Task: {task['task_id']}\n")  
            f.write(f"Task Index: {task_idx}\n")
            f.write(f"Entry Point: {task['entry_point']}\n")  
            f.write(f"Code File: {found_path}\n")  
            f.write(f"Result: {result[0]}\n")  
            f.write(f"Details: {result[1]}\n")  
            f.write(f"\nGenerated Code:\n{generated_code}\n")  
        print(f"\n评测结果已保存到: {result_file}")  
    else:  
        _logger.error(f"✗ 错误: 未找到包含函数 '{task['entry_point']}' 的代码文件")
        print(f"\n✗ 错误: 未找到包含函数 '{task['entry_point']}' 的代码文件")  
  
  
if __name__ == "__main__":  
    parser = argparse.ArgumentParser(description="Run a specific HumanEval task with MetaGPT")
    parser.add_argument(
        "--defense",
        default=None,
    )
    parser.add_argument(
        "--project-path",
        default="./humaneval_baseline",
        help="Directory where MetaGPT will generate the project (default: ./humaneval_baseline)",
    )
    args = parser.parse_args()

    if args.defense:
        os.environ["METAGPT_DEFENSE_TYPE"] = args.defense.strip().lower()

    # 读取 HumanEval 
    humaneval_path = "../human-eval/data/HumanEval.jsonl" 
    humaneval_tasks = []
    with open(humaneval_path, "r") as f:  
        for line in f:
            humaneval_tasks.append(json.loads(line))

    # if not (0 <= args.task_idx < len(humaneval_tasks)):
    #     raise IndexError(f"task_idx {args.task_idx} 超出范围 0-{len(humaneval_tasks)-1}")

    for idx, task in enumerate(humaneval_tasks):
        print(f"运行任务索引: {idx}")
        print(f"任务详情: {task}")

        project_path = args.project_path
        run_humaneval_with_metagpt(idx, task, project_path)
        print(f"运行完成: {idx}")
