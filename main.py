from fastapi import FastAPI, HTTPException, Request, Body
from pydantic import BaseModel
from typing import List
import os
from mistralai import Mistral
from dotenv import load_dotenv
import pymysql
from datetime import datetime
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
from langchain.prompts import ChatPromptTemplate
from langchain_mistralai.chat_models import ChatMistralAI
from langchain.output_parsers import PydanticOutputParser
from pydantic import Field

app = FastAPI()

# Structured output models
class KPI(BaseModel):
    name: str = Field(description="Name of the KPI")
    formula: str = Field(description="Mathematical formula for the KPI")
    description: str = Field(description="Brief explanation of the KPI")

class KPIList(BaseModel):
    kpis: List[KPI]
    summary: str = Field(description="Executive summary of the KPIs")

# Initialize LangChain components
parser = PydanticOutputParser(pydantic_object=KPIList)

kpi_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a senior business analyst with 20 years of experience. Generate professional KPIs."),
    ("human", 
     "I'm a {position} in the {department} department at a {sector} company. "
     "Generate 5 KPIs with formulas to measure: {project}. "
     "Use industry-standard terminology.\n\n{format_instructions}")
])

# Data models
class QuestionRequest(BaseModel):
    question: str = ""
    id_user: int  

class Session(BaseModel):
    id: int
    id_user: int
    date: datetime

class ProfileModel(BaseModel):
    id_user: int
    position: str
    department: str
    sector: str

class ProjectRequest(BaseModel):
    id_user: int
    project: str

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables
load_dotenv()
api_key = os.getenv("MISTRAL_API_KEY")

# Initialize Mistral client through LangChain
model = ChatMistralAI(
    model="mistral-small-2402",
    mistral_api_key=api_key
)

# Create processing chain
# Check if `|` is the correct operator in LangChain
chain = model | parser

# Database connection
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

# Endpoints
@app.get("/api/user")
def get_user_id(request: Request):
    try:
        cursor.execute("SELECT FLOOR(RAND() * 999999) + 1 AS id_user")  # RAandom user ID
        result = cursor.fetchone()
        if result:
            id_user = int(result['id_user'])
            
            cursor.execute("INSERT INTO user (id_user) VALUES (%s)", (id_user,))
            cursor.execute("INSERT INTO session (id_user) VALUES (%s)", (id_user,))
            cursor.execute("INSERT INTO profile (id_user) VALUES (%s)", (id_user,))
            db.commit()
            return {"status": "success", "id_user": id_user}
        else:
            raise HTTPException(status_code=404, detail="Failed to generate user ID.")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

@app.post("/v1/profile")
async def create_profile(profile: ProfileModel):
    try:
        cursor.execute("SELECT * FROM profile WHERE id_user = %s", (profile.id_user,))
        existing_profile = cursor.fetchone()

        if existing_profile:
            cursor.execute("""
                UPDATE profile
                SET position = %s, department = %s, sector = %s
                WHERE id_user = %s
            """, (profile.position, profile.department, profile.sector, profile.id_user))
        else:
            cursor.execute("""
                INSERT INTO profile (id_user, position, department, sector)
                VALUES (%s, %s, %s, %s)
            """, (profile.id_user, profile.position, profile.department, profile.sector))
        db.commit()
        return {"message": "Profile updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/v1/project")
async def add_project(project_req: ProjectRequest):
    try:
        cursor.execute("INSERT INTO project (id_user, project) VALUES (%s, %s)", 
                       (project_req.id_user, project_req.project))
        db.commit()
        return {"message": "Project added successfully", "id_project": cursor.lastrowid}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/v1/generate-question")
def generate_question(req: QuestionRequest):
    id_user = req.id_user
    try:
        cursor.execute("""
            SELECT p.position, p.department, p.sector, pr.project, pr.id_project
            FROM profile p 
            JOIN project pr ON p.id_user = pr.id_user 
            WHERE p.id_user = %s 
            ORDER BY pr.id_project DESC LIMIT 1
        """, (id_user,))
        profile_data = cursor.fetchone()
        if not profile_data:
            raise HTTPException(status_code=404, detail="Profile or Project not found")

        # Generate formatted prompt
        prompt = kpi_prompt.format(
            position=profile_data['position'],
            department=profile_data['department'],
            sector=profile_data['sector'],
            project=profile_data['project'],
            format_instructions=parser.get_format_instructions()
        )

        cursor.execute("SELECT id FROM session WHERE id_user = %s ORDER BY date DESC LIMIT 1", (id_user,))
        session_id = cursor.fetchone()["id"]

        cursor.execute("INSERT INTO question (id, question) VALUES (%s, %s)",
                       (session_id, prompt))
        db.commit()

        return {"status": "success", "question": prompt}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/v1/ask")
def ask_mistral(req: QuestionRequest):
    id_user = req.id_user
    try:
        cursor.execute("SELECT id FROM session WHERE id_user = %s ORDER BY date DESC LIMIT 1", (id_user,))
        session_id = cursor.fetchone()["id"]

        cursor.execute(
            "SELECT id_question, question FROM question WHERE id = %s ORDER BY id_question DESC LIMIT 1",
            (session_id,)
        )
        question_data = cursor.fetchone()
        if not question_data:
            raise HTTPException(status_code=404, detail="No question found")

        
        cursor.execute("""
            SELECT p.position, p.department, p.sector, pr.project 
            FROM profile p
            JOIN project pr ON p.id_user = pr.id_user
            WHERE p.id_user = %s
            ORDER BY pr.id_project DESC LIMIT 1
        """, (id_user,))
        context = cursor.fetchone()

        
        prompt_str = kpi_prompt.format(
            position=context['position'],
            department=context['department'],
            sector=context['sector'],
            project=context['project'],
            format_instructions=parser.get_format_instructions()
        )

        
        result = chain.invoke(prompt_str)

        
        cursor.execute(
            "INSERT INTO answer (id_question, id, answer) VALUES (%s, %s, %s)",
            (question_data["id_question"], session_id, result.json())
        )
        db.commit()


        return {"message": result.json()}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")



@app.get("/v1/db", response_model=List[Session])
def get_sessions():
    try:
        cursor.execute("SELECT * FROM session")
        return cursor.fetchall()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

app.mount("/", StaticFiles(directory=".", html=True), name="static")        