from fastapi import FastAPI, HTTPException, Request
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

app = FastAPI()

class QuestionRequest(BaseModel):
    question: str
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
    project: str

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

load_dotenv()
api_key = os.getenv("MISTRAL_API_KEY")
model = "mistral-small-2402"

# Conexión con la base de datos
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

@app.get("/api/user")
def get_user_ip(request: Request):
    try:
        cursor.execute("SELECT FLOOR(RAND() * (999999 - 1 + 1) + 1) AS id_user")
        result = cursor.fetchone()
        id_user = str(result['id_user'])

        # Crear las entradas correspondientes en las tablas
        cursor.execute("INSERT INTO session (id_user) VALUES (%s)", (id_user,))
        cursor.execute("INSERT INTO profile (id_user) VALUES (%s)", (id_user,))
        cursor.execute("INSERT INTO project (id_user) VALUES (%s)", (id_user,))
        db.commit()

        return {"status": "success", "id_user": id_user}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail=f"Database error: {str(e)}")

@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

@app.post("/v1/profile")
async def create_profile(profile: ProfileModel):
    try:
        # Verificar si el perfil ya existe en la tabla profile
        cursor.execute("SELECT * FROM profile WHERE id_user = %s", (profile.id_user,))
        existing_profile = cursor.fetchone()

        if existing_profile:
            # Si el perfil ya existe, actualizar los campos en profile
            cursor.execute("""
                UPDATE profile
                SET position = %s, department = %s, sector = %s
                WHERE id_user = %s
            """, (profile.position, profile.department, profile.sector, profile.id_user))
            db.commit()
        else:
            # Si el perfil no existe, crearlo en profile
            cursor.execute("""
                INSERT INTO profile (id_user, position, department, sector)
                VALUES (%s, %s, %s, %s)
            """, (profile.id_user, profile.position, profile.department, profile.sector))
            db.commit()

        # Independientemente de si se creó o actualizó el perfil,
        # actualizar la tabla project con el valor recibido.
        cursor.execute("UPDATE project SET project = %s WHERE id_user = %s", (profile.project, profile.id_user))
        db.commit()

        return {"message": "Profile updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")



@app.post("/v1/generate-question")
def generate_question(req: QuestionRequest):
    id_user = req.id_user

    try:
        # Consulta JOIN para obtener profile y el último project del usuario.
        cursor.execute("""
            SELECT p.position, p.department, p.sector, pr.project 
            FROM profile p 
            JOIN project pr ON p.id_user = pr.id_user 
            WHERE p.id_user = %s 
            ORDER BY pr.id_project DESC LIMIT 1
        """, (id_user,))
        profile_data = cursor.fetchone()
        if not profile_data:
            raise HTTPException(status_code=404, detail="Profile or Project not found for user")

        # Crear el prompt basado en los datos del perfil y proyecto
        prompt = (
            f"You are a business analyst expert. I am a {profile_data['position']} at the {profile_data['department']} "
            f"department in a company operating in {profile_data['sector']}, and I want 5 KPIs with their formulas "
            f"for measuring {profile_data['project']}."
        )

        # Obtener el id de la sesión (columna 'id' en la tabla session) para este usuario
        cursor.execute("SELECT id FROM session WHERE id_user = %s ORDER BY date DESC LIMIT 1", (id_user,))
        session_data = cursor.fetchone()
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found for user")
        session_id = session_data["id"]

        # Guardar la pregunta en la tabla question usando el id de sesión
        cursor.execute("INSERT INTO question (id, question) VALUES (%s, %s)", (session_id, prompt))
        db.commit()

        return {"status": "success", "question": prompt}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")



@app.post("/v1/ask")
def ask_mistral(req: QuestionRequest):
    id_user = req.id_user

    try:
        # Obtener el id de la sesión (session id) usando el id_user
        cursor.execute("SELECT id FROM session WHERE id_user = %s ORDER BY date DESC LIMIT 1", (id_user,))
        session_data = cursor.fetchone()
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found for user")
        session_id = session_data["id"]

        # Obtener la última pregunta registrada para este session_id
        cursor.execute(
            "SELECT id_question, question FROM question WHERE id = %s ORDER BY id_question DESC LIMIT 1",
            (session_id,)
        )
        question_data = cursor.fetchone()
        if not question_data:
            raise HTTPException(status_code=404, detail="No question found for user")
        prompt = question_data["question"]
        id_question = question_data["id_question"]

        # Llamar al modelo LLM con el prompt generado
        client = Mistral(api_key)
        chat_response = client.chat.complete(
            model=model,
            messages=[{"role": "user", "content": prompt}]
        )
        answer = chat_response.choices[0].message.content

        # Guardar la respuesta en la base de datos en la tabla answer
        cursor.execute(
            "INSERT INTO answer (id_question, id, answer) VALUES (%s, %s, %s)",
            (id_question, session_id, answer)
        )
        db.commit()

        return {"message": answer}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")



@app.get("/v1/db", response_model=List[Session])
def get_sessions():
    try:
        cursor.execute("SELECT * FROM session")
        return cursor.fetchall()
    except Exception as e:
        print(f"DB Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

app.mount("/", StaticFiles(directory=".", html=True), name="static")
