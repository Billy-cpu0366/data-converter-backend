"""
稳定版本API：使用JSON格式，零处理显示
"""

from fastapi import FastAPI, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from openai import OpenAI
import os
import json
import pandas as pd
from io import BytesIO, StringIO
import re
import docx
import hashlib

# 加载环境变量（用于本地开发）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 生产环境可能没有安装 python-dotenv，这是正常的
    pass

# 配置
API_KEY = os.getenv("OPENROUTER_API_KEY")
if not API_KEY:
    raise ValueError("OPENROUTER_API_KEY environment variable is required")

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
MODEL_NAME = "openai/gpt-4.1-mini"

app = FastAPI()

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", 
        "http://127.0.0.1:3000",
        "https://mizhoudpdns.dpdns.org",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=API_KEY, base_url=OPENROUTER_API_BASE)

# 文件处理函数
def process_docx_file(file_content: bytes) -> str:
    """提取docx文本，保留格式"""
    try:
        doc = docx.Document(BytesIO(file_content))
        all_text = []
        for para in doc.paragraphs:
            text = para.text
            if text.strip():
                all_text.append(text)
        return "\n".join(all_text)
    except Exception as e:
        return f"[DOCX解析错误] {str(e)}"

def process_excel_file(file_content: bytes) -> str:
    """提取Excel文本，保留格式"""
    try:
        xls = pd.ExcelFile(BytesIO(file_content))
        all_text = []
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name)
            all_text.append(f"=== {sheet_name} ===")
            for _, row in df.iterrows():
                row_text = " | ".join(str(cell) if pd.notna(cell) else "" for cell in row)
                if row_text.strip():
                    all_text.append(row_text)
        return "\n".join(all_text)
    except Exception as e:
        return f"[EXCEL解析错误] {str(e)}"

def decode_text(raw_data: bytes) -> str:
    """解码文本，保留所有字符"""
    encodings = ['utf-8', 'gbk', 'gb2312', 'latin-1']
    for encoding in encodings:
        try:
            return raw_data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_data.decode('latin-1', errors='replace')

def extract_quiz_data(text: str) -> list:
    """AI提取题目，但保留原始文本"""
    system_prompt = """你是一个精确的题库提取机器人。从文本中提取所有选择题，保持原文完整不变。

要求：
1. **绝对保真**：题目文本必须100%保留原文，包括所有空格、换行符、代码缩进
2. **完整提取**：提取完整的C语言程序代码，禁止任何截断或简化
3. **格式保持**：保持原文的所有格式，换行符用\\n表示，制表符用\\t表示
4. **特殊字符**：保留所有特殊字符，包括括号、分号、大括号等

输出格式：
{
  "questions": [
    {
      "raw_question": "完整题目原文，包括所有C代码和换行符",
      "raw_options": ["选项A原文", "选项B原文", "选项C原文", "选项D原文"],
      "raw_answer": "正确答案字母"
    }
  ]
}

重要：
- 禁止简化C语言程序代码，必须完整保留！
- 保留所有缩进和空格
- 换行符必须保留
- 代码中的注释也要保留"""

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请以JSON格式提取以下文本中的题目：\n\n{text}"}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(completion.choices[0].message.content)
        questions = result.get("questions", [])

        # 添加字段映射，确保兼容性
        for i, q in enumerate(questions):
            # 如果AI返回的是 question 字段，映射到 raw_question
            if "question" in q and "raw_question" not in q:
                q["raw_question"] = q["question"]
            if "options" in q and "raw_options" not in q:
                q["raw_options"] = q["options"]
            if "answer" in q and "raw_answer" not in q:
                q["raw_answer"] = q["answer"]

            # 检测是否包含代码
            question_text = q.get("raw_question", "")
            q["has_code"] = bool(re.search(r'#include|int\s+main|printf|scanf|for\s*\(|while\s*\(|if\s*\(|void\s+|char\s+|float\s+|double\s+', question_text))

            # 添加完整性校验
            q["metadata"] = q.get("metadata", {})
            q["metadata"]["checksum"] = hashlib.md5(
                (q.get("raw_question", "") + str(q.get("raw_options", []))).encode()
            ).hexdigest()[:8]

        return questions
        
    except Exception as e:
        return [{"error": str(e), "raw_text": text[:200]}]

def create_stable_html(questions: list, mode: str = "random") -> str:
    """生成稳定的HTML，零处理显示"""
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>题库练习 - 共{len(questions)}题</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .raw-text {{ white-space: pre-wrap; word-break: break-word; }}
        .code-question {{
            font-family: 'Courier New', 'Monaco', 'Menlo', monospace;
            background-color: #f8f9fa;
            border-left: 4px solid #007acc;
            padding: 0.75rem;
            border-radius: 0.5rem;
            line-height: 1.3;
            overflow-x: auto;
            white-space: pre-wrap;
            font-size: 0.9rem;
            max-height: 400px;
            overflow-y: auto;
        }}
        .option-btn {{ transition: all 0.2s; }}
        .option-btn:hover {{ background-color: #f3f4f6; }}
        .selected {{ background-color: #dbeafe; border-color: #3b82f6; }}
        .correct {{ background-color: #dcfce7; border-color: #22c55e; }}
        .incorrect {{ background-color: #fef2f2; border-color: #ef4444; }}
    </style>
</head>
<body class="bg-gray-100 font-sans">
    <div class="container mx-auto p-4 max-w-4xl">
        


        <!-- 主显示区域 -->
        <div class="bg-white rounded-lg shadow-lg p-6">
            
            <!-- 进度条 -->
            <div class="mb-6">
                <div class="flex justify-between text-sm text-gray-600 mb-2">
                    <span>进度</span>
                    <span id="progress-text">1 / {len(questions)}</span>
                </div>
                <div class="w-full bg-gray-200 rounded-full h-2">
                    <div id="progress-bar" class="bg-blue-500 h-2 rounded-full" style="width: {100/len(questions)}%"></div>
                </div>
            </div>

            <!-- 题目显示 -->
            <div class="mb-4">
                <div class="text-sm text-gray-500 mb-2">第 <span id="question-number">1</span> 题</div>
                <div id="question-text" class="raw-text text-lg text-gray-800 mb-4 p-3 bg-gray-50 rounded"></div>
            </div>

            <!-- 选项显示 -->
            <div id="options-container" class="space-y-2">
            </div>

            <!-- 导航按钮 -->
            <div class="mt-8 flex justify-between items-center">
                <button id="prev-btn" class="px-6 py-2 bg-gray-300 text-gray-700 rounded hover:bg-gray-400 disabled:opacity-50" disabled>上一题</button>
                <button id="restart-btn" class="px-4 py-2 bg-red-500 text-white rounded hover:bg-red-600 text-sm">重新开始</button>
                <button id="next-btn" class="px-6 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50">下一题</button>
            </div>

            <!-- 底部导航 -->
            <div class="mt-6 pt-4 border-t">
                <div class="text-sm text-gray-500 mb-2">快速导航:</div>
                <div id="nav-buttons" class="flex flex-wrap gap-2">
                </div>
            </div>
        </div>

        <!-- 警告提示 -->
        <div id="warnings" class="mt-4 hidden">
            <div class="bg-yellow-50 border-l-4 border-yellow-400 p-4">
                <div class="flex">
                    <div class="ml-3">
                        <p class="text-sm text-yellow-700">
                            <strong>数据警告:</strong>
                            <span id="warning-text"></span>
                        </p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // 原始数据（零处理）
        const originalQuestions = {json.dumps(questions, ensure_ascii=False, indent=2)};
        
        // 数据处理
        let questions = originalQuestions.map((q, index) => ({{
            ...q,
            index: index,
            userAnswer: null,
            isAnswered: false
        }}));

        let currentIndex = 0;
        const mode = "{mode}";

        // 随机化函数
        function shuffleArray(array) {{
            const shuffled = [...array];
            for (let i = shuffled.length - 1; i > 0; i--) {{
                const j = Math.floor(Math.random() * (i + 1));
                [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
            }}
            return shuffled;
        }}

        // 随机化题目和选项
        function randomizeQuestions() {{
            if (mode === "random") {{
                // 随机化题目顺序
                questions = shuffleArray(questions);

                // 随机化每个题目的选项顺序
                questions.forEach(q => {{
                    if (q.raw_options && q.raw_options.length > 0) {{
                        // 保存正确答案的索引
                        const correctIndex = 'ABCD'.indexOf(q.raw_answer);

                        // 创建选项和索引的配对
                        const optionPairs = q.raw_options.map((opt, idx) => ({{ option: opt, originalIndex: idx }}));

                        // 随机化选项
                        const shuffledPairs = shuffleArray(optionPairs);

                        // 更新选项数组
                        q.raw_options = shuffledPairs.map(pair => pair.option);

                        // 找到正确答案的新位置
                        const newCorrectIndex = shuffledPairs.findIndex(pair => pair.originalIndex === correctIndex);
                        q.raw_answer = 'ABCD'[newCorrectIndex];
                    }}
                }});
            }}
        }}

        // 初始随机化
        randomizeQuestions();

        // 安全地显示文本，保留格式
        function safeDisplayText(text) {{
            if (!text) return '';
            // 先进行HTML转义
            let escaped = text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');

            // 处理换行符和制表符
            escaped = escaped.split('\\n').join('<br>');
            escaped = escaped.split('\\t').join('&nbsp;&nbsp;&nbsp;&nbsp;');
            escaped = escaped.replace(/  /g, '&nbsp;&nbsp;');

            return escaped;
        }}

        // 显示题目
        function displayQuestion(index) {{
            const q = questions[index];

            // 更新进度 - 显示当前位置序号（与底部导航一致）
            document.getElementById('question-number').textContent = index + 1;
            document.getElementById('progress-text').textContent = `${{index + 1}} / ${{questions.length}}`;
            document.getElementById('progress-bar').style.width = `${{(index + 1) / questions.length * 100}}%`;

            // 显示题目 - 去掉题目序号
            const questionElement = document.getElementById('question-text');
            let questionText = q.raw_question;

            // 去掉题目开头的序号（如"1. "、"2. "等）
            questionText = questionText.replace(/^\d+\.\s*/, '');

            questionElement.innerHTML = safeDisplayText(questionText);

            // 如果包含代码，应用代码样式
            if (q.has_code) {{
                questionElement.classList.add('code-question');
            }} else {{
                questionElement.classList.remove('code-question');
            }}
            
            // 显示选项
            const optionsHtml = q.raw_options.map((opt, i) => {{
                // 清理选项文本，移除已有的字母前缀
                let cleanOpt = opt.trim();
                if (cleanOpt.match(/^[A-Z]\\.\s*/)) {{
                    cleanOpt = cleanOpt.replace(/^[A-Z]\\.\s*/, '');
                }}

                return `
                <button class="option-btn w-full text-left p-3 border rounded-lg raw-text"
                        data-index="${{i}}"
                        onclick="selectAnswer(${{i}})">
                    ${{String.fromCharCode(65 + i)}}. ${{cleanOpt || '[空选项]'}}
                </button>
                `;
            }}).join('');
            document.getElementById('options-container').innerHTML = optionsHtml;
            
            // 更新按钮状态
            document.getElementById('prev-btn').disabled = index === 0;
            document.getElementById('next-btn').disabled = index === questions.length - 1;
            
            // 高亮当前导航
            document.querySelectorAll('#nav-buttons button').forEach((btn, i) => {{
                btn.className = `px-3 py-1 text-sm rounded ${{
                    i === index ? 'bg-blue-500 text-white' : 'bg-gray-200 hover:bg-gray-300'
                }}`;
            }});
            
            // 显示之前的选择
            if (q.userAnswer !== null) {{
                const buttons = document.querySelectorAll('#options-container button');
                buttons.forEach((btn, i) => {{
                    btn.disabled = true;
                    if (i === q.userAnswer) {{
                        btn.classList.add(q.userAnswer === 'ABCD'.indexOf(q.raw_answer) ? 'correct' : 'incorrect');
                    }}
                }});
            }}
        }}

        function selectAnswer(answerIndex) {{
            const q = questions[currentIndex];
            q.userAnswer = answerIndex;
            q.isAnswered = true;

            const correctAnswerIndex = 'ABCD'.indexOf(q.raw_answer);
            const buttons = document.querySelectorAll('#options-container button');

            buttons.forEach((btn, i) => {{
                btn.disabled = true;
                if (i === answerIndex) {{
                    // 用户选择的选项：正确显示绿色，错误显示红色
                    btn.classList.add(answerIndex === correctAnswerIndex ? 'correct' : 'incorrect');
                }} else if (i === correctAnswerIndex) {{
                    // 如果用户答错了，同时显示正确答案（绿色）
                    btn.classList.add('correct');
                }}
            }});
        }}

        // 创建导航按钮
        function createNavButtons() {{
            const container = document.getElementById('nav-buttons');
            // 清空现有按钮，避免重复
            container.innerHTML = '';

            questions.forEach((q, i) => {{
                const btn = document.createElement('button');
                btn.textContent = i + 1;
                btn.onclick = () => {{
                    currentIndex = i;
                    displayQuestion(currentIndex);
                }};
                btn.className = 'px-3 py-1 text-sm rounded bg-gray-200 hover:bg-gray-300';
                container.appendChild(btn);
            }});
        }}

        // 绑定上一题/下一题按钮
        document.getElementById('prev-btn').addEventListener('click', () => {{
            if (currentIndex > 0) {{
                currentIndex--;
                displayQuestion(currentIndex);
                // 移除自动滚动，保持用户当前滚动位置
            }}
        }});
        document.getElementById('next-btn').addEventListener('click', () => {{
            if (currentIndex < questions.length - 1) {{
                currentIndex++;
                displayQuestion(currentIndex);
                // 移除自动滚动，保持用户当前滚动位置
            }}
        }});

        // 绑定重新开始按钮
        document.getElementById('restart-btn').addEventListener('click', () => {{
            if (confirm('确定要重新开始吗？这将清除所有已选答案。')) {{
                // 重置题目数据为原始状态
                questions = originalQuestions.map((q, index) => ({{
                    ...q,
                    index: index,
                    userAnswer: null,
                    isAnswered: false
                }}));

                // 如果是随机模式，重新随机化
                randomizeQuestions();

                // 回到第一题
                currentIndex = 0;
                displayQuestion(currentIndex);

                // 重新创建导航按钮
                createNavButtons();
            }}
        }});

        // 键盘快捷键：左右方向键切题
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'ArrowLeft') {{
                const btn = document.getElementById('prev-btn');
                if (!btn.disabled) btn.click();
            }} else if (e.key === 'ArrowRight') {{
                const btn = document.getElementById('next-btn');
                if (!btn.disabled) btn.click();
            }}
        }});

        // 初始化
        createNavButtons();
        if (questions.length > 0) {{
            displayQuestion(currentIndex);
        }} else {{
            document.getElementById('question-text').textContent = '没有可显示的题目';
            document.getElementById('options-container').innerHTML = '';
            document.getElementById('prev-btn').disabled = true;
            document.getElementById('next-btn').disabled = true;
        }}
    </script>
</body>
</html>"""
    
    return html

@app.post("/convert-stable")
async def convert_data_stable(file: UploadFile = File(...)):
    """稳定版本转换API"""
    raw_data = await file.read()
    filename = file.filename.lower() if file.filename else ""
    
    try:
        # 提取文本
        if filename.endswith('.docx'):
            text = process_docx_file(raw_data)
        elif filename.endswith(('.xlsx', '.xls')):
            text = process_excel_file(raw_data)
        else:
            text = decode_text(raw_data)
        
        # 提取题目
        questions = extract_quiz_data(text)
        
        # 统计
        total_questions = len(questions)
        valid_questions = [q for q in questions if not q.get("error")]
        
        return JSONResponse(content={
            "success": True,
            "total_questions": total_questions,
            "questions": valid_questions,
            "warnings": [],
            "source_filename": filename,
            "checksum": hashlib.md5(str(questions).encode()).hexdigest()[:8]
        })
        
    except Exception as e:
        return JSONResponse(content={
            "success": False,
            "error": str(e),
            "questions": []
        }, status_code=500)

@app.post("/generate-stable-practice")
async def generate_stable_practice(request: Request):
    """生成稳定练习页面"""
    data = await request.json()
    questions = data.get("questions", [])
    mode = data.get("mode", "random")

    # 添加详细调试信息 - stable_api.py
    print(f"\n🔍 [STABLE_API] 前端发送的数据调试:")
    print(f"题目数量: {len(questions)}")
    for i, q in enumerate(questions[:3]):  # 只显示前3道题
        print(f"题目{i+1}:")
        print(f"  raw_question: {repr(q.get('raw_question', ''))[:100]}...")
        print(f"  raw_options: {q.get('raw_options', [])}")
        print(f"  raw_answer: {q.get('raw_answer', '')}")
        print(f"  has_code: {q.get('has_code', False)}")

    if not questions:
        return JSONResponse(content={"error": "没有题目数据"}, status_code=400)

    html = create_stable_html(questions, mode)
    return HTMLResponse(content=html)

@app.get("/stable")
def stable_root():
    return {"message": "稳定版本API已就绪"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)