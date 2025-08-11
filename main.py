from fastapi import FastAPI, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from openai import OpenAI, APIConnectionError
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

# --- Configuration ---
API_KEY = os.getenv("OPENROUTER_API_KEY")
if not API_KEY:
    raise ValueError("OPENROUTER_API_KEY environment variable is required")

OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
MODEL_NAME = "openai/gpt-4.1-mini"

# --- FastAPI App Initialization ---
app = FastAPI()

origins = [
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:3002",
    "http://localhost:3003",
    "http://localhost:3004",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:3002",
    "http://127.0.0.1:3003",
    "http://127.0.0.1:3004",
    "https://data-converter-frontend.pages.dev",
    "https://mizhoudpdns.dpdns.org",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- OpenAI Client Initialization ---
client = OpenAI(
    api_key=API_KEY,
    base_url=OPENROUTER_API_BASE,
)

# --- Helper Functions (from stable_api.py) ---

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
        
        # 优先处理"单选"工作表
        target_sheets = [sheet for sheet in xls.sheet_names if "单选" in str(sheet)]
        if not target_sheets:
            target_sheets = xls.sheet_names[:1]  # 如果没有"单选"，用第一个工作表
            
        for sheet_name in target_sheets:
            try:
                df = pd.read_excel(xls, sheet_name=sheet_name)
                all_text.append(f"=== {sheet_name} ===")
                
                # 确保有数据
                if not df.empty:
                    # 处理列名
                    columns = [str(col) if pd.notna(col) else f"列{i}" for i, col in enumerate(df.columns)]
                    
                    # 处理每一行
                    for idx, row in df.iterrows():
                        row_data = []
                        for i, cell in enumerate(row):
                            cell_str = str(cell) if pd.notna(cell) else ""
                            if cell_str.strip():  # 只添加非空内容
                                col_name = columns[i] if i < len(columns) else f"列{i}"
                                row_data.append(f"{col_name}: {cell_str}")
                        
                        if row_data:  # 如果有有效数据
                            all_text.append("\n".join(row_data))
                            all_text.append("---")  # 分隔符
                            
            except Exception as sheet_error:
                all_text.append(f"[工作表错误] {sheet_name}: {str(sheet_error)}")
                
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
- 代码中的注释也要保留
- 只返回JSON格式数据，不要添加任何解释文字
- 确保返回的是有效的JSON格式"""

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请分析以下文本并以JSON格式返回提取的题目数据：\n\n{text}"}
            ],
            temperature=0.1
        )

        # 获取AI响应内容
        ai_content = completion.choices[0].message.content
        print(f"AI原始响应: {ai_content[:500]}...")

        # 尝试提取JSON内容
        try:
            # 如果AI返回的是纯JSON
            result = json.loads(ai_content)
        except json.JSONDecodeError:
            # 如果AI返回的包含其他文本，尝试提取JSON部分
            import re as regex_module
            json_match = regex_module.search(r'\{.*\}', ai_content, regex_module.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                raise ValueError("无法从AI响应中提取有效的JSON数据")
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

        # 添加调试信息
        print(f"AI提取的原始数据: {questions}")
        print(f"提取到的题目数量: {len(questions)}")
        for i, q in enumerate(questions):
            print(f"题目{i+1}: {q}")
            if q.get('error'):
                print(f"  错误信息: {q['error']}")

        return questions

    except Exception as e:
        error_msg = str(e)
        print(f"AI提取过程中发生异常: {error_msg}")
        return [{"error": error_msg, "raw_text": text[:200]}]

def create_stable_html(questions: list, mode: str = "random") -> str:
    """生成稳定的HTML，零处理显示
    兼容以下字段格式：
    - 标准：raw_question, raw_options(list[str]), raw_answer(字母或文本)
    - 兼容：question, options, answer, correctOptionIndex(0-based)
    """
    # 统一题目数据结构，避免前端显示为空
    normalized = []
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for q in questions or []:
        rq = q.get("raw_question") or q.get("question") or q.get("title") or ""
        ro = q.get("raw_options") or q.get("options") or []
        # 兼容字典形式 {A:...,B:...}
        if isinstance(ro, dict):
            ro = [ro.get(k) for k in sorted(ro.keys())]
        if not isinstance(ro, list):
            ro = []
        ro = ["" if v is None else str(v) for v in ro]
        ra = q.get("raw_answer")
        if ra is None:
            if "correctOptionIndex" in q:
                try:
                    idx = int(q.get("correctOptionIndex"))
                    if 0 <= idx < len(letters):
                        ra = letters[idx]
                except Exception:
                    ra = None
            elif "answer" in q:
                ra = str(q.get("answer")).strip()
        # 检测是否包含代码
        has_code = bool(re.search(r'#include|int\s+main|printf|scanf|for\s*\(|while\s*\(|if\s*\(|void\s+|char\s+|float\s+|double\s+', rq))
        normalized.append({
            "raw_question": str(rq),
            "raw_options": ro,
            "raw_answer": (str(ra) if ra is not None else ""),
            "has_code": has_code,
        })

    html = f"""<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
    <meta charset=\"UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>题库练习 - 共{len(normalized)}题</title>
    <script src=\"https://cdn.tailwindcss.com\"></script>
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
        const originalQuestions = {json.dumps(normalized, ensure_ascii=False)};

        // 调试：检查数据传递
        console.log('原始题目数据:', originalQuestions);
        console.log('第一道题目内容:', originalQuestions[0]?.raw_question);

        // 数据处理
        let questions = originalQuestions.map((q, index) => ({{
            ...q,
            index: index,
            userAnswer: null,
            isAnswered: false
        }}));

        console.log('处理后的题目数据:', questions);
        console.log('第一道题目处理后:', questions[0]?.raw_question);

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

        // 显示题目
        function displayQuestion(index) {{
            const q = questions[index];

            // 调试：检查题目数据
            console.log(`显示第${{index + 1}}题:`, q);
            console.log('题目原始内容:', q.raw_question);

            // 更新进度 - 显示当前位置序号（与底部导航一致）
            document.getElementById('question-number').textContent = index + 1;
            document.getElementById('progress-text').textContent = `${{index + 1}} / ${{questions.length}}`;
            document.getElementById('progress-bar').style.width = `${{(index + 1) / questions.length * 100}}%`;

            // 显示题目 - 去掉题目序号
            const questionElement = document.getElementById('question-text');
            let questionText = q.raw_question || '';

            console.log('题目处理前:', questionText);
            console.log('questionElement:', questionElement);

            // 去掉题目开头的序号（如"1. "、"2. "等）
            questionText = questionText.replace(/^\\d+\\.\\s*/, '');

            console.log('题目处理后:', questionText);

            // 强制显示题目内容 - 使用textContent保持原始格式
            if (questionText.trim()) {{
                console.log('设置题目内容:', questionText);

                // 如果包含代码，需要保留换行符和格式
                if (q.has_code) {{
                    // 对于代码题目，使用innerHTML并转义HTML特殊字符
                    const escapedText = questionText
                        .replace(/&/g, '&amp;')
                        .replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;')
                        .replace(/"/g, '&quot;')
                        .replace(/'/g, '&#39;');
                    questionElement.innerHTML = escapedText;
                }} else {{
                    // 对于普通题目，使用textContent
                    questionElement.textContent = questionText;
                }}

                questionElement.style.display = 'block';
                questionElement.style.visibility = 'visible';
            }} else {{
                console.error('题目内容为空！');
                questionElement.textContent = '题目内容为空';
            }}

            // 如果包含代码，应用代码样式
            if (q.has_code) {{
                questionElement.classList.add('code-question');
            }} else {{
                questionElement.classList.remove('code-question');
            }}
            
            // 显示选项 - 使用DOM创建而不是innerHTML
            const optionsContainer = document.getElementById('options-container');
            optionsContainer.innerHTML = ''; // 清空容器

            q.raw_options.forEach((opt, i) => {{
                // 清理选项文本，移除已有的字母前缀
                let cleanOpt = opt.trim();
                if (cleanOpt.match(/^[A-Z]\\.\\s*/)) {{
                    cleanOpt = cleanOpt.replace(/^[A-Z]\\.\\s*/, '');
                }}

                // 创建按钮元素
                const button = document.createElement('button');
                button.className = 'option-btn w-full text-left p-3 border rounded-lg raw-text';
                button.dataset.index = i;
                button.textContent = `${{String.fromCharCode(65 + i)}}. ${{cleanOpt || '[空选项]'}}`;  // 使用textContent
                button.addEventListener('click', () => selectAnswer(i));

                optionsContainer.appendChild(button);
            }});
            
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

@app.post("/convert")
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

        # 添加调试信息
        print(f"处理文件: {filename}")
        print(f"提取的文本长度: {len(text)}")
        print(f"提取的文本前500字符: {text[:500]}")
        print(f"API密钥前10位: {API_KEY[:10]}...")
        
        # 提取题目
        questions = extract_quiz_data(text)
        
        # 统计
        total_questions = len(questions)
        valid_questions = [q for q in questions if not q.get("error")]
        error_questions = [q for q in questions if q.get("error")]

        print(f"总题目数: {total_questions}")
        print(f"有效题目数: {len(valid_questions)}")
        print(f"错误题目数: {len(error_questions)}")

        # 临时返回所有数据用于调试
        return JSONResponse(content={
            "success": True,
            "total_questions": total_questions,
            "questions": valid_questions,
            "all_questions": questions,  # 包含所有数据用于调试
            "error_questions": error_questions,  # 错误的题目
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

    # 添加详细调试信息
    print(f"\n🔍 前端发送的数据调试:")
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

@app.get("/test-api")
def test_api():
    """测试API连接"""
    try:
        print(f"测试API连接，使用密钥: {API_KEY[:10]}...")
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": "Hello, please respond with 'API test successful'"}],
            max_tokens=20
        )
        response_text = completion.choices[0].message.content
        print(f"API测试成功，响应: {response_text}")
        return {"status": "success", "response": response_text, "model": MODEL_NAME}
    except Exception as e:
        error_msg = str(e)
        print(f"API测试失败: {error_msg}")
        return {"status": "error", "error": error_msg}

@app.get("/")
def read_root():
    return {"message": "Backend is running and configured for OpenRouter."}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8001))  # Render 会提供 PORT 环境变量
    uvicorn.run(app, host="0.0.0.0", port=port)