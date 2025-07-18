

from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from openai import OpenAI
import os
import json
import pandas as pd
from io import BytesIO
import re

# --- Configuration ---
API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
MODEL_NAME = "openai/gpt-4.1-mini"

# Define chunking parameters
MAX_CHUNK_SIZE_CHARS = 10000  # Max characters per chunk (adjust based on model token limits)
CHUNK_OVERLAP_CHARS = 500     # Overlap to ensure context is not lost at boundaries

# --- FastAPI App Initialization ---
app = FastAPI()

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- OpenAI Client Initialization ---
if not API_KEY:
    print("CRITICAL ERROR: OPENROUTER_API_KEY environment variable not set.")

client = OpenAI(
    api_key=API_KEY,
    base_url=OPENROUTER_API_BASE,
)

# --- Helper Functions ---

def decode_text(raw_data: bytes) -> str:
    encodings_to_try = ['utf-8', 'gbk', 'gb2312', 'latin-1']
    for encoding in encodings_to_try:
        try:
            return raw_data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""

def process_excel_file(file_content: bytes) -> str:
    try:
        # Read all sheets from the Excel file
        xls = pd.ExcelFile(BytesIO(file_content))
        all_sheets_text = []
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name)
            # Convert each sheet to CSV string, then append
            all_sheets_text.append(f"\n--- Sheet: {sheet_name} ---\n")
            all_sheets_text.append(df.to_csv(index=False))
        return "\n".join(all_sheets_text)
    except Exception as e:
        print(f"Error processing Excel file: {e}")
        raise ValueError(f"Failed to process Excel file: {e}")

def parse_ai_json_response(ai_response_str: str):
    try:
        # Try to extract JSON from markdown code block first
        json_match = re.search(r'```json\n(.*)\n```', ai_response_str, re.DOTALL)
        if json_match:
            json_content = json_match.group(1)
        else:
            json_content = ai_response_str # Assume it's pure JSON if no markdown block
        
        parsed_json = json.loads(json_content)
        
        converted_data = None
        # Try to find a list within the top-level values of the JSON
        if isinstance(parsed_json, dict):
            for value in parsed_json.values():
                if isinstance(value, list):
                    converted_data = value
                    break
        
        # If no list found, try to use the whole parsed_json if it's a list
        if converted_data is None and isinstance(parsed_json, list):
            converted_data = parsed_json

        if converted_data is None:
            # Fallback: if AI returns a single object, wrap it in a list
            if isinstance(parsed_json, dict):
                converted_data = [parsed_json]
            else:
                raise ValueError("AI did not return a valid JSON array or object that could be converted.")
        
        return converted_data

    except json.JSONDecodeError as e:
        raise ValueError(f"AI returned invalid JSON: {e}. Raw AI response: {ai_response_str[:500]}...")
    except ValueError as e:
        raise ValueError(f"AI response could not be converted to expected format: {e}. Raw AI response: {ai_response_str[:500]}...")

def generate_quiz_html(quiz_data: list) -> str:
    processed_quiz_data = []
    for question_item in quiz_data:
        processed_question = question_item.copy()
        if 'options' in processed_question and isinstance(processed_question['options'], dict):
            processed_question['options'] = list(processed_question['options'].values())
        processed_quiz_data.append(processed_question)

    quiz_data_json = json.dumps(processed_quiz_data, ensure_ascii=False)

    html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Practice Quiz</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f4f4f4; color: #333; }
        .container { max-width: 800px; margin: 0 auto; background-color: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { text-align: center; color: #0056b3; margin-bottom: 30px; }
        .question-card { background-color: #e9f5ff; border: 1px solid #cce7ff; border-radius: 6px; padding: 20px; margin-bottom: 20px; }
        .question-text { font-size: 1.2em; margin-bottom: 15px; line-height: 1.5; }
        .options label { display: block; margin-bottom: 10px; cursor: pointer; font-size: 1.1em; }
        .options input[type="radio"] { margin-right: 10px; }
        .feedback { margin-top: 15px; font-weight: bold; }
        .correct { color: green; }
        .incorrect { color: red; }
        .navigation-buttons { text-align: center; margin-top: 30px; }
        .navigation-buttons button { background-color: #007bff; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-size: 1em; margin: 0 10px; }
        .navigation-buttons button:hover { background-color: #0056b3; }
        .navigation-buttons button:disabled { background-color: #cccccc; cursor: not-allowed; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Practice Quiz</h1>
        <div id="quiz-container"></div>
        <div class="navigation-buttons">
            <button id="prev-btn" disabled>Previous</button>
            <button id="next-btn">Next</button>
        </div>
    </div>

    <script>
        const quizDataElement = document.createElement('div');
        quizDataElement.style.display = 'none';
        quizDataElement.setAttribute('id', 'quiz-data');
        quizDataElement.setAttribute('data-quiz', `{quiz_data_placeholder}`);
        document.body.appendChild(quizDataElement);

        let currentQuestionIndex = 0;
        let questions = [];

        try {
            const rawQuizData = document.getElementById('quiz-data').getAttribute('data-quiz');
            questions = JSON.parse(rawQuizData);
        } catch (e) {
            console.error("Error parsing quiz data:", e);
            document.getElementById("quiz-container").innerHTML = "<p style=\"color: red;\">Error loading quiz data. Please check the data format.</p>";
        }

        function indexToLetter(index) {
            return String.fromCharCode(65 + index); // 65 is ASCII for 'A'
        }

        function displayQuestion() {
            if (questions.length === 0) {
                document.getElementById("quiz-container").innerHTML = "<p>No questions available.</p>";
                return;
            }
            const question = questions[currentQuestionIndex];
            const quizContainer = document.getElementById("quiz-container");
            quizContainer.innerHTML = `
                <div class="question-card">
                    <div class="question-text">${currentQuestionIndex + 1}. ${question.question}</div>
                    <div class="options">
                        ${question.options.map((option, index) => `
                            <label>
                                <input type="radio" name="q${currentQuestionIndex}" value="${option}" onchange="checkAnswer()">
                                ${indexToLetter(index)}. ${option}
                            </label>
                        `).join('')}
                    </div>
                    <div class="feedback" id="feedback-${currentQuestionIndex}"></div>
                </div>
            `;
            updateNavigationButtons();
        }

        function checkAnswer() {
            const question = questions[currentQuestionIndex];
            const selectedOption = document.querySelector(`input[name="q${currentQuestionIndex}"]:checked`);
            const feedbackDiv = document.getElementById(`feedback-${currentQuestionIndex}`);

            if (selectedOption) {
                const correctOptionIndex = question.options.indexOf(question.answer);
                const correctAnswerLetter = indexToLetter(correctOptionIndex);

                if (selectedOption.value === question.answer) {
                    feedbackDiv.className = 'feedback correct';
                    feedbackDiv.textContent = 'Correct!';
                } else {
                    feedbackDiv.className = 'feedback incorrect';
                    feedbackDiv.textContent = `Incorrect. The correct answer is: ${correctAnswerLetter}. ${question.answer}`;
                }
            } else {
                feedbackDiv.className = 'feedback';
                feedbackDiv.textContent = '';
            }
        }

        function updateNavigationButtons() {
            document.getElementById("prev-btn").disabled = currentQuestionIndex === 0;
            document.getElementById("next-btn").disabled = currentQuestionIndex === questions.length - 1;
        }

        document.getElementById("next-btn").addEventListener("click", () => {
            if (currentQuestionIndex < questions.length - 1) {
                currentQuestionIndex++;
                displayQuestion();
            }
        });

        document.getElementById("prev-btn").addEventListener("click", () => {
            if (currentQuestionIndex > 0) {
                currentQuestionIndex--;
                displayQuestion();
            }
        });

        document.addEventListener("DOMContentLoaded", displayQuestion);
    </script>
</body>
</html>
"""
    html_content = html_template.format(quiz_data_placeholder=quiz_data_json)
    return html_content

# --- API Endpoints ---

@app.post("/generate-practice-page", response_class=HTMLResponse)
async def generate_practice_page(quiz_data: list):
    print("Received quiz_data:", quiz_data)
    try:
        html_output = generate_quiz_html(quiz_data)
        return HTMLResponse(content=html_output, media_type="text/html")
    except Exception as e:
        return JSONResponse(content={"error": f"Failed to generate practice page: {str(e)}"}, status_code=500)
@app.post("/convert")
async def convert_data(file: UploadFile = File(...)):
    if not API_KEY:
        return JSONResponse(content={"error": "API Key is not configured on the server."}, status_code=500)

    raw_data = await file.read()
    unstructured_data_text = ""

    # Determine file type and process accordingly
    if file.filename.endswith('.xlsx') or file.filename.endswith('.xls'):
        try:
            unstructured_data_text = process_excel_file(raw_data)
        except ValueError as e:
            return JSONResponse(content={"error": str(e)}, status_code=400)
    else:
        # Assume it's a text-based file (txt, csv, etc.)
        unstructured_data_text = decode_text(raw_data)
        if not unstructured_data_text:
            return JSONResponse(content={"error": "Could not decode file content. It might be a binary file or use an unsupported text encoding."}, status_code=400)

    # --- Chunking and AI Call Loop ---
    all_converted_items = []
    start_index = 0
    total_length = len(unstructured_data_text)

    while start_index < total_length:
        end_index = min(start_index + MAX_CHUNK_SIZE_CHARS, total_length)
        chunk = unstructured_data_text[start_index:end_index]

        # Adjust start_index for the next chunk with overlap
        if end_index < total_length:
            start_index = end_index - CHUNK_OVERLAP_CHARS
            # Ensure start_index doesn't go negative
            if start_index < 0: start_index = 0
        else:
            start_index = total_length # End the loop

        # Create a clear, structured prompt for the AI for this chunk
        system_prompt = """You are an expert quiz data extraction tool. Your task is to convert unstructured text into a structured JSON array of quiz questions. Each object in the array must contain 'question' (string), 'options' (an array of strings for choices), and 'answer' (string, the correct option). You must only return a valid JSON array. Do not include any markdown formatting like ```json or any explanatory text. If no quiz data is found in this chunk, return an empty JSON array []."""
        user_prompt = f"""This is a part of a larger document. Please process the following text chunk:

---
{chunk}

Based on the text above, please extract quiz questions, their options, and the correct answer. Ensure 'options' is an array of strings and 'answer' is one of the options."""

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
            
            # Parse the AI's JSON response for this chunk
            chunk_converted_data = parse_ai_json_response(ai_response_str)
            all_converted_items.extend(chunk_converted_data)

        except Exception as e:
            print(f"An error occurred during AI call for a chunk: {e}")
            # Return an error response if any chunk fails
            return JSONResponse(content={"error": f"An error occurred while processing a chunk with AI: {str(e)}. Raw AI response: {ai_response_str[:200] if 'ai_response_str' in locals() else ''}..."}, status_code=500)

    # Return the final structured data to the frontend
    final_response = {
        "message": "Conversion successful!",
        "original_filename": file.filename,
        "converted_data": all_converted_items
    }
    return JSONResponse(content=final_response)

@app.get("/")
def read_root():
    return {"message": "Backend is running and configured for OpenRouter."}
