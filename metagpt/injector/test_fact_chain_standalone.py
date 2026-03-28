"""独立测试事实链条（Fact Chain）注入功能（不依赖 MetaGPT 环境）"""

import re
from pathlib import Path

def inject_fact_chain_standalone(context: str, pg19_text_path: str = None):
    """
    独立的事实链条注入函数（用于测试）
    """
    if pg19_text_path is None:
        pg19_text_path = "/Users/ximenajia/CODE/Tester/pg19/downloaded_data/10146.txt"
    
    pg19_path = Path(pg19_text_path)
    
    if not pg19_path.exists():
        print(f"错误: PG-19 文本文件不存在: {pg19_text_path}")
        return None, False
    
    try:
        # 读取 PG-19 文本
        with open(pg19_path, "r", encoding="utf-8") as f:
            pg19_text = f.read()
        
        print(f"✓ 已加载 PG-19 文本: {len(pg19_text)} 字符")
        
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
            print(f"警告: 片段数量不足 ({len(fact_fragments)})")
            return None, False
        
        print(f"✓ 已拆解为 {len(fact_fragments)} 个事实片段:")
        for i, fragment in enumerate(fact_fragments, 1):
            print(f"  片段 {i}: {fragment[:60]}...")
        
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
        
        print(f"\n插入位置:")
        for i, pos in enumerate(positions, 1):
            print(f"  位置 {i}: {pos} ({pos/text_length*100:.1f}%)")
        
        # 创建插入后的文本
        result_text = pg19_text
        offset = 0  # 跟踪插入导致的偏移
        
        # 按位置从后往前插入，避免位置偏移问题
        insertions = list(zip(positions, fact_fragments))
        insertions.sort(reverse=True)  # 从后往前排序
        
        for pos, fragment in insertions:
            # 找到合适的插入点（在句子或段落边界）
            actual_pos = pos + offset
            
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
            
            # 插入事实片段（更自然的插入方式）
            if insert_point > 0 and result_text[insert_point-1] != '\n':
                fragment_with_context = f" {fragment}. "
            else:
                fragment_with_context = f"\n\n{fragment}.\n\n"
            
            result_text = result_text[:insert_point] + fragment_with_context + result_text[insert_point:]
            offset += len(fragment_with_context)
            
            print(f"  ✓ 在位置 {insert_point} 插入片段: {fragment[:40]}...")
        
        print(f"\n✓ 注入完成！")
        print(f"  原始文本长度: {len(pg19_text)} 字符")
        print(f"  结果文本长度: {len(result_text)} 字符")
        print(f"  增加长度: {len(result_text) - len(pg19_text)} 字符")
        
        return result_text, True
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return None, False


def main():
    """主测试函数"""
    
    # 测试消息（包含多个事实，参考 BABILong 示例）
    test_message = """
    老王今天穿了一件红色的衬衫。
    老王在公园丢了一张蓝色的卡片。
    捡到蓝色卡片的人会得到一件和失主衬衫颜色一样的礼物。
    这个礼物是一本关于历史的书籍。
    书籍的封面是红色的，与衬衫颜色相同。
    """
    
    print("=" * 60)
    print("测试事实链条（Fact Chain）注入功能")
    print("=" * 60)
    print(f"\n原始消息长度: {len(test_message)} 字符")
    print(f"\n原始消息内容:\n{test_message}")
    print("\n" + "=" * 60)
    print()
    
    # 执行注入
    result, success = inject_fact_chain_standalone(test_message)
    
    if success and result:
        print("\n" + "=" * 60)
        print("结果预览")
        print("=" * 60)
        
        # 检查原始消息中的关键事实是否都在结果中
        key_facts = ["红色", "蓝色", "卡片", "礼物", "衬衫", "老王"]
        found_facts = []
        for fact in key_facts:
            if fact in result:
                found_facts.append(fact)
        
        print(f"\n关键事实检查:")
        print(f"  原始消息中的关键事实: {key_facts}")
        print(f"  结果中找到的事实: {found_facts}")
        print(f"  覆盖率: {len(found_facts)}/{len(key_facts)} = {len(found_facts)/len(key_facts)*100:.1f}%")
        
        # 显示插入位置的上下文
        print(f"\n插入位置上下文预览:")
        text_length = len(result)
        positions = [
            int(text_length * 0.10),
            int(text_length * 0.50),
            int(text_length * 0.90),
        ]
        
        for i, pos in enumerate(positions, 1):
            start = max(0, pos - 100)
            end = min(len(result), pos + 100)
            context = result[start:end]
            print(f"\n  位置 {i} ({pos/text_length*100:.1f}%) 上下文:")
            print(f"  {context[:200]}...")
    else:
        print("\n✗ 注入失败")


if __name__ == "__main__":
    main()

