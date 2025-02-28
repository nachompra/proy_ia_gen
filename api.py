from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import os
from mistralai import Mistral
from dotenv import load_dotenv
import pymysql
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Initialize app FIRST
app = FastAPI()

# Add CORS middleware SECOND
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables THIRD
load_dotenv()
api_key = os.getenv("MISTRAL_API_KEY")
model = "mistral-small-2402"

# Database connection FOURTH
try:
    db = pymysql.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PW"),
        database="kpi_database",
        cursorclass=pymysql.cursors.DictCursor
    )
    cursor = db.cursor()
except Exception as e:
    print(f"Database connection error: {str(e)}")
    raise RuntimeError("Database connection failed") from e

# Define models FIFTH
class QuestionRequest(BaseModel):
    question: str

class Session(BaseModel):
    id: int
    prompt: str
    answer: str
    date: datetime

# API routes SIXTH
@app.post("/v1/ask")
def ask_mistral(req: QuestionRequest):
    try:
        client = Mistral(api_key)
        chat_response = client.chat.complete(
            model=model,
            messages=[{"role": "user", "content": req.question}]
        )
        answer = chat_response.choices[0].message.content
        
        cursor.execute(
            "INSERT INTO session (prompt, answer) VALUES (%s, %s)",
            (req.question, answer)
        )  # Fixed line
        db.commit()
        return {"message": answer}
        
    except Exception as e:
        db.rollback()
        print(f"API Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/db", response_model=List[Session])
def get_sessions():
    try:
        cursor.execute("SELECT * FROM session")
        return cursor.fetchall()
    except Exception as e:
        print(f"DB Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Static files LAST
app.mount("/", StaticFiles(directory=".", html=True), name="static")