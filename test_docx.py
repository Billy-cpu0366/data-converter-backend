#!/usr/bin/env python3
import os
import sys
sys.path.append('.')

# 直接导入需要的函数
import docx
import re

def process_docx_file(raw_data):
    """处理 docx 文件并提取文本"""
    from io import BytesIO
    doc = docx.Document(BytesIO(raw_data))
    text = []
    for paragraph in doc.paragraphs:
        text.append(paragraph.text)
    return '\n'.join(text)

def extract_quiz_questions_simple(text):
    """
    从文本中提取题目数据
    支持多种格式:
    格式1: 标准格式
    1. 题目内容
    A. 选项1
    B. 选项2
    【答案】A

    格式2: 用户文档格式
    题目内容
    A选项1
    B选项2
    答案：A
    """
    questions = []

    # 支持两种答案格式
    if "【答案】" in text or "答案：" in text or "答案:" in text:
        # 简单的正则表达式解析
        question_blocks = re.split(r'\n\s*\n', text)
        for block in question_blocks:
            # 检查是否包含答案
            if any(keyword in block for keyword in ["【答案】", "答案：", "答案:"]):
                lines = [line.strip() for line in block.strip().split('\n') if line.strip()]
                if len(lines) >= 3:
                    # 提取题目 - 第一行通常是题目
                    question_line = lines[0]
                    question = re.sub(r'^\d+\.\s*', '', question_line)

                    options = []
                    answer_line = ""

                    for line in lines[1:]:
                        # 匹配多种选项格式: A. 选项 或 A选项
                        if re.match(r'^[A-D][\.\s]', line):
                            # A. 选项 格式
                            option_text = re.sub(r'^[A-D][\.\s]+', '', line)
                            options.append(option_text)
                        elif re.match(r'^[A-D][^A-D\s]', line):
                            # A选项 格式（没有点或空格）
                            option_text = line[1:]  # 去掉第一个字符（A/B/C/D）
                            options.append(option_text)
                        elif any(keyword in line for keyword in ['答案：', '答案:', '【答案】']):
                            answer_line = line
                            break

                    if len(options) >= 2:
                        # 提取正确答案
                        correct_index = 0
                        if '【答案】' in answer_line:
                            answer_match = re.search(r'【答案】([A-D])', answer_line)
                            if answer_match:
                                correct_index = ord(answer_match.group(1)) - ord('A')
                        elif '答案：' in answer_line:
                            answer_match = re.search(r'答案：([A-D])', answer_line)
                            if answer_match:
                                correct_index = ord(answer_match.group(1)) - ord('A')
                        elif '答案:' in answer_line:
                            answer_match = re.search(r'答案:([A-D])', answer_line)
                            if answer_match:
                                correct_index = ord(answer_match.group(1)) - ord('A')

                        questions.append({
                            'question': question,
                            'options': options,
                            'correctOptionIndex': correct_index
                        })

    return questions

def test_docx_files():
    # 查找当前目录中的所有 .docx 文件
    docx_files = [f for f in os.listdir('.') if f.endswith('.docx')]
    
    if not docx_files:
        print("没有找到 .docx 文件")
        print("当前目录中的文件:")
        for f in os.listdir('.'):
            print(f"  {f}")
        return
    
    for filename in docx_files:
        print(f"\n{'='*50}")
        print(f"处理文件: {filename}")
        print(f"{'='*50}")
        
        try:
            # 读取文件
            with open(filename, 'rb') as f:
                raw_data = f.read()
            
            print(f"文件大小: {len(raw_data)} 字节")
            
            # 处理 docx 文件
            text_content = process_docx_file(raw_data)
            print(f"提取的文本长度: {len(text_content)}")
            print(f"完整文本内容:")
            print(repr(text_content))
            print(f"\n是否包含【答案】: {'【答案】' in text_content}")
            print(f"是否包含'答案': {'答案' in text_content}")
            
            # 尝试提取题目
            questions = extract_quiz_questions_simple(text_content)
            print(f"\n提取到的题目数量: {len(questions)}")
            
            if questions:
                for i, q in enumerate(questions[:3], 1):  # 只显示前3个题目
                    print(f"\n题目 {i}:")
                    print(f"  问题: {q.get('question', 'N/A')}")
                    print(f"  选项: {q.get('options', [])}")
                    print(f"  正确答案索引: {q.get('correctOptionIndex', 'N/A')}")
            else:
                print("没有找到题目")
                
                # 尝试分析文本结构
                print("\n文本分析:")
                lines = text_content.split('\n')
                print(f"总行数: {len(lines)}")
                
                # 查找可能的题目模式
                question_patterns = []
                for i, line in enumerate(lines[:50]):  # 只检查前50行
                    line = line.strip()
                    if line:
                        if any(char.isdigit() for char in line[:5]):  # 前5个字符中有数字
                            question_patterns.append(f"行 {i+1}: {repr(line[:100])}")
                
                if question_patterns:
                    print("可能的题目行:")
                    for pattern in question_patterns[:10]:  # 只显示前10个
                        print(f"  {pattern}")
                
        except Exception as e:
            print(f"处理文件 {filename} 时出错: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    test_docx_files()
