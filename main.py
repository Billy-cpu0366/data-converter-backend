from fastapi import FastAPI, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from openai import OpenAI, APIConnectionError
import os
import json
import pandas as pd
from io import BytesIO
import re
import docx

# --- Configuration ---
API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
MODEL_NAME = "openai/gpt-4.1-mini"

# --- FastAPI App Initialization ---
app = FastAPI()

# --- Startup Check ---
if not API_KEY:
    raise SystemExit("CRITICAL ERROR: OPENROOUTER_API_KEY environment variable not set. The application cannot start.")

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://data-converter-frontend.pages.dev",
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

# --- Helper Functions ---

def process_docx_file(file_content: bytes) -> str:
    """Extracts text from a .docx file."""
    try:
        doc = docx.Document(BytesIO(file_content))
        all_text = [p.text for p in doc.paragraphs]
        return "\n".join(all_text)
    except Exception as e:
        print(f"Error processing DOCX file: {e}")
        raise ValueError(f"Failed to process DOCX file: {e}")

def decode_text(raw_data: bytes) -> str:
    """Tries to decode raw bytes using a list of common encodings."""
    encodings_to_try = ['utf-8', 'gbk', 'gb2312', 'latin-1']
    for encoding in encodings_to_try:
        try:
            return raw_data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""

def process_excel_file(file_content: bytes) -> str:
    """Extracts text from all sheets of an Excel file and formats it as CSV."""
    try:
        xls = pd.ExcelFile(BytesIO(file_content))
        all_sheets_text = []
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name)
            all_sheets_text.append(f"\n--- Sheet: {sheet_name} ---\n")
            all_sheets_text.append(df.to_csv(index=False))
        return "\n".join(all_sheets_text)
    except Exception as e:
        print(f"Error processing Excel file: {e}")
        raise ValueError(f"Failed to process Excel file: {e}")

def parse_ai_json_response(ai_response_str: str) -> list:
    """
    Parses the JSON response from the AI. It now expects the answer to be a letter (A, B, C, D)
    and converts it to a zero-based index. It no longer performs any escaping/decoding.
    """
    try:
        json_start_index = ai_response_str.find('{')
        if json_start_index == -1:
            print(f"Warning: No JSON object found in AI response. Raw: {ai_response_str[:500]}...")
            return []

        parsed_json = json.loads(ai_response_str[json_start_index:])

        if not isinstance(parsed_json, dict) or "questions" not in parsed_json:
            print(f"Warning: AI response JSON did not have the expected 'questions' key. Raw: {ai_response_str[:500]}...")
            return []

        raw_questions = parsed_json.get("questions", [])
        if not isinstance(raw_questions, list):
            print(f"Warning: 'questions' in AI response is not a list. Raw: {ai_response_str[:500]}...")
            return []

        transformed_questions = []
        for q in raw_questions:
            if not isinstance(q, dict):
                print(f"Warning: Question item is not a dictionary: {q}")
                continue

            raw_question = q.get("raw_question", "")
            raw_options = q.get("raw_options", [])
            raw_answer = q.get("raw_answer", "").strip().upper()

            if not raw_question or not isinstance(raw_options, list) or not raw_answer:
                print(f"Warning: Missing required fields (raw_question, raw_options, raw_answer) in question: {q}")
                continue

            # Convert answer letter ('A', 'B', 'C', 'D') to a zero-based index.
            correct_option_index = -1
            if raw_answer in "ABCD":
                correct_option_index = "ABCD".find(raw_answer)
            else:
                print(f"Warning: Invalid raw_answer '{raw_answer}' received from AI for question '{raw_question}'. Expected 'A', 'B', 'C', or 'D'.")

            transformed_questions.append({
                "question": raw_question,
                "options": raw_options,
                "correctOptionIndex": correct_option_index
            })
        return transformed_questions

    except json.JSONDecodeError as e:
        print(f"Error: AI returned invalid JSON: {e}. Raw: {ai_response_str[:500]}...")
        return []
    except Exception as e:
        print(f"An unexpected error occurred in parse_ai_json_response: {e}. Raw: {ai_response_str[:500]}...")
        return []

def generate_quiz_html(quiz_data: list, mode: str) -> str:
    """Generates the final HTML page using the template file."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, 'templates', 'index.html')

    try:
        with open(template_path, "r", encoding="utf-8") as f:
            html_template = f.read()
    except FileNotFoundError:
        raise ValueError("The template file 'templates/index.html' was not found.")

    json_data = json.dumps(quiz_data, ensure_ascii=False)
    
    # 将 JSON 数据注入到数据岛中
    final_html = html_template.replace(
        '/*__QUIZ_DATA_PLACEHOLDER__*/',
        json_data
    )
    final_html = final_html.replace(
        "const questionOrderMode = 'random'",
        f"const questionOrderMode = '{mode}'"
    )
    
    return final_html

# --- API Endpoints ---

@app.post("/generate-practice-page", response_class=HTMLResponse)
async def generate_practice_page(request: Request):
    data = await request.json()
    quiz_data = data.get("quiz_data")
    mode = data.get("mode", "random")

    if not isinstance(quiz_data, list):
        return JSONResponse(content={"error": f"Invalid quiz data format: expected a list, got {type(quiz_data).__name__}."}, status_code=400)

    try:
        html_output = generate_quiz_html(quiz_data, mode)
        return HTMLResponse(content=html_output, media_type="text/html")
    except Exception as e:
        print(f"Error generating practice page: {e}")
        return JSONResponse(content={"error": f"Failed to generate practice page: {str(e)}"}, status_code=500)

@app.post("/convert")
async def convert_data(file: UploadFile = File(...)):
    raw_data = await file.read()
    filename = file.filename.lower() if file.filename else ""

    try:
        if filename.endswith('.docx'):
            unstructured_data_text = process_docx_file(raw_data)
        elif filename.endswith(('.xlsx', '.xls')):
            unstructured_data_text = process_excel_file(raw_data)
        else:
            unstructured_data_text = decode_text(raw_data)
            if not unstructured_data_text:
                return JSONResponse(content={"error": "Could not decode file. It might be binary or use an unsupported encoding."}, status_code=400)
    except ValueError as e:
        return JSONResponse(content={"error": str(e)}, status_code=400)

    system_prompt = """你是一个高度精确的题库提取机器人. 你的核心任务是从用户提供的文本中, 一字不差地提取出所有选择题, 并以稳定、纯净的JSON格式输出.

**核心指令:**

1.  **绝对保真**:
    *   **题目 (`raw_question`)**: 必须与原文100%一致, 包括所有的空格、换行符 (`\n`)、制表符 (`\t`)、代码缩进和特殊字符. **严禁进行任何形式的转义或格式修改.**
    *   **选项 (`raw_options`)**: 同样必须保持绝对原文.

2.  **答案提取与标准化**:
    *   在题目文本中找到 `【答案】X` 这样的标记.
    *   提取这个标记中的字母 `X`.
    *   **答案 (`raw_answer`)**: 必须将提取到的字母标准化为单个大写字母: `A`, `B`, `C`, 或 `D`.

3.  **严格的JSON输出**:
    *   只输出一个顶级的JSON对象.
    *   JSON对象必须包含一个名为 `questions` 的键, 其值为一个数组.
    *   如果文本中没有找到任何有效的题目, 返回 `{\"questions\": []}`.

**处理范例:**

*   **如果原文是:**
    ```
    1. 有以下程序：
    char fun(char x, char y)
    {
      if(x)
        return y;
    }
    void main()
    {
      char a='9',b='8',c='7';
      printf("%c\n", fun(fun(a,b), fun(b,c)));
    }
    程序运行后的输出结果是( ).
    A. 9
    B. 8
    C. 7
    D. 语法错误
    【答案】B
    ```

*   **你必须输出:**
    ```json
    {
      "questions": [
        {
          "raw_question": "1. 有以下程序：\nchar fun(char x, char y)\n{\n  if(x)\n    return y;\n}\nvoid main()\n{\n  char a='9',b='8',c='7';\n  printf(\"\\\"%c\\\\n\\\"", fun(fun(a,b), fun(b,c)));\n}\n程序运行后的输出结果是( ).",
          "raw_options": [
            "9",
            "8",
            "7",
            "语法错误"
          ],
          "raw_answer": "B"
        }
      ]
    }
    ```
"""

    user_prompt = f"""Please process the following text and extract all quiz questions from it according to the specified JSON format:

---
{unstructured_data_text}
---
"""

    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        ai_response_str = completion.choices[0].message.content
        converted_data = parse_ai_json_response(ai_response_str)

    except APIConnectionError as e:
        print(f"AI API Connection Error: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "无法连接到 AI 服务。请检查您的网络连接和代理设置。如果在中国大陆使用，请确保已正确配置全局代理。"}
        )
    except Exception as e:
        print(f"An error occurred during the AI call: {type(e).__name__}: {e}")
        return JSONResponse(content={"error": f"An error occurred while processing with AI: {str(e)}"}, status_code=500)

    final_response = {
        "message": "Conversion successful!",
        "original_filename": file.filename,
        "converted_data": converted_data
    }
    return JSONResponse(content=final_response)

@app.get("/")
def read_root():
    return {"message": "Backend is running and configured for OpenRouter."}