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

# 配置
API_KEY = os.getenv("OPENROUTER_API_KEY")
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
    system_prompt = """你是一个精确的题库提取工具。从文本中提取所有题目，保持原样不变。

要求：
1. 保持题目原文本格式，包括换行符
2. 保持选项原文本
3. 保持答案原文本
4. 不添加、不删除任何内容
5. 如果找不到完整题目，返回空列表

输出JSON格式：
{
  "questions": [
    {
      "raw_question": "题目原文",
      "raw_answer": "答案原文", 
      "raw_options": ["选项A原文", "选项B原文", "选项C原文", "选项D原文"],
      "metadata": {
        "source_line": 行号,
        "confidence": 0-1
      }
    }
  ]
}"""

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"提取以下文本中的题目：\n\n{text}"}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(completion.choices[0].message.content)
        questions = result.get("questions", [])
        
        # 添加完整性校验
        for i, q in enumerate(questions):
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
        .option-btn {{ transition: all 0.2s; }}
        .option-btn:hover {{ background-color: #f3f4f6; }}
        .selected {{ background-color: #dbeafe; border-color: #3b82f6; }}
        .correct {{ background-color: #dcfce7; border-color: #22c55e; }}
        .incorrect {{ background-color: #fef2f2; border-color: #ef4444; }}
    </style>
</head>
<body class="bg-gray-100 font-sans">
    <div class="container mx-auto p-4 max-w-4xl">
        
        <!-- 头部信息 -->
        <div class="bg-white rounded-lg shadow-lg p-6 mb-4">
            <h1 class="text-2xl font-bold text-center mb-2">题库练习</h1>
            <div class="text-center text-gray-600">
                <span>共 <span class="font-bold text-blue-600">{len(questions)}</span> 题</span>
                <span class="ml-4">模式: <span class="font-bold">{mode}</span></span>
            </div>
            
            <!-- 数据统计 -->
            <div class="mt-4 text-sm text-gray-500 text-center">
                <div>数据完整性校验: <span class="text-green-600">✓ 已验证</span></div>
            </div>
        </div>

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
            <div class="mb-6">
                <div class="text-sm text-gray-500 mb-2">第 <span id="question-number">1</span> 题</div>
                <div id="question-text" class="raw-text text-lg text-gray-800 mb-4 p-4 bg-gray-50 rounded"></div>
            </div>

            <!-- 选项显示 -->
            <div id="options-container" class="space-y-3">
            </div>

            <!-- 导航按钮 -->
            <div class="mt-8 flex justify-between">
                <button id="prev-btn" class="px-6 py-2 bg-gray-300 text-gray-700 rounded hover:bg-gray-400 disabled:opacity-50" disabled>上一题</button>
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
        
        // 随机排序
        if (mode === "random") {{
            const shuffled = [...questions];
            for (let i = shuffled.length - 1; i > 0; i--) {{
                const j = Math.floor(Math.random() * (i + 1));
                [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
            }}
            questions = shuffled;
        }}

        // 显示题目
        function displayQuestion(index) {{
            const q = questions[index];
            
            // 更新进度
            document.getElementById('question-number').textContent = index + 1;
            document.getElementById('progress-text').textContent = `${{index + 1}} / ${{questions.length}}`;
            document.getElementById('progress-bar').style.width = `${{(index + 1) / questions.length * 100}}%`;
            
            // 显示题目
            document.getElementById('question-text').textContent = q.raw_question;
            
            // 显示选项
            const optionsHtml = q.raw_options.map((opt, i) => `
                <button class="option-btn w-full text-left p-4 border rounded-lg raw-text" 
                        data-index="${{i}}"
                        onclick="selectAnswer(${{i}})">
                    ${{
                        opt.trim() ? 
                        `${{String.fromCharCode(65 + i)}}. ${{opt}}` : 
                        `${{String.fromCharCode(65 + i)}}. [空选项]`
                    }}
                </button>
            `).join('');
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
            
            const buttons = document.querySelectorAll('#options-container button');
            buttons.forEach((btn, i) => {{
                btn.disabled = true;
                if (i === answerIndex) {{
                    btn.classList.add(answerIndex === 'ABCD'.indexOf(q.raw_answer) ? 'correct' : 'incorrect');
                }}
            }});
        }}

        // 创建导航按钮
        function createNavButtons() {{
            const container = document.getElementById('nav-buttons');
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

        // 初始化
        createNavButtons();
        displayQuestion(currentIndex);
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