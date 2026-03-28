"""测试事实链条（Fact Chain）注入功能"""

import sys
from pathlib import Path

# 添加 MetaGPT 目录到路径
meta_gpt_dir = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(meta_gpt_dir))

# 现在可以导入
from metagpt.injector.Tester2 import FaultInjector, InjectorConfig

def test_fact_chain_injection():
    """测试事实链条注入"""
    
    # 加载配置
    config = InjectorConfig()
    
    # 创建测试用的故障注入器配置
    test_config = {
        "rule_id": "fact_chain_injection",
        "llm_model": "gpt-5-mini",  # 虽然不会用到，但需要提供
        "temperature": 0.7,
        "llm_api_key": config.llm_injection.get("llm_api_key", ""),
        "llm_base_url": config.llm_injection.get("llm_base_url", ""),
        "rules_yaml_path": "rules.yaml",
        "agent_intro_yaml_path": "MetaGPT_intro.yaml",
    }
    
    # 创建注入器
    injector = FaultInjector(test_config)
    
    # 测试消息（包含多个事实）
    test_message = """
    老王今天穿了一件红色的衬衫。
    老王在公园丢了一张蓝色的卡片。
    捡到蓝色卡片的人会得到一件和失主衬衫颜色一样的礼物。
    这个礼物是一本关于历史的书籍。
    书籍的封面是红色的，与衬衫颜色相同。
    """
    
    print("=" * 60)
    print("测试事实链条注入")
    print("=" * 60)
    print(f"\n原始消息长度: {len(test_message)} 字符")
    print(f"\n原始消息内容:\n{test_message}")
    print("\n" + "=" * 60)
    
    # 执行注入
    result, success = injector.inject(
        context=test_message,
        agent_name="TestAgent",
        goal="测试事实链条注入功能",
        receiver_name=None
    )
    
    if success:
        print(f"\n✓ 注入成功！")
        print(f"结果长度: {len(result)} 字符")
        print(f"\n结果预览（前500字符）:\n{result[:500]}...")
        print(f"\n结果预览（中间500字符）:\n{result[len(result)//2:len(result)//2+500]}...")
        print(f"\n结果预览（后500字符）:\n{result[-500:]}")
        
        # 检查原始消息中的关键事实是否都在结果中
        key_facts = ["红色", "蓝色", "卡片", "礼物", "衬衫"]
        found_facts = []
        for fact in key_facts:
            if fact in result:
                found_facts.append(fact)
        
        print(f"\n关键事实检查:")
        print(f"  原始消息中的关键事实: {key_facts}")
        print(f"  结果中找到的事实: {found_facts}")
        print(f"  覆盖率: {len(found_facts)}/{len(key_facts)} = {len(found_facts)/len(key_facts)*100:.1f}%")
    else:
        print(f"\n✗ 注入失败")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    test_fact_chain_injection()

