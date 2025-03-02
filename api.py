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

app = FastAPI()

# Modelos de datos
class QuestionRequest(BaseModel):
    question: str = ""   # Ya no se usa directamente, pero se conserva por compatibilidad
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

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cargar variables de entorno y configuración del modelo LLM
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

# Evento startup para agregar la columna id_project en la tabla question si no existe
@app.on_event("startup")
def startup_event():
    try:
        cursor.execute("SHOW COLUMNS FROM question LIKE 'id_project'")
        result = cursor.fetchone()
        if not result:
            cursor.execute("ALTER TABLE question ADD COLUMN id_project INT")
            db.commit()
            print("Columna id_project agregada a la tabla question.")
        else:
            print("La columna id_project ya existe en la tabla question.")
    except Exception as e:
        print(f"Error al verificar/agregar la columna id_project: {str(e)}")

# Endpoint para generar un id de usuario y crear las entradas básicas en session y profile
@app.get("/api/user")
def get_user_ip(request: Request):
    try:
        cursor.execute("SELECT FLOOR(RAND() * (999999 - 1 + 1) + 1) AS id_user")
        result = cursor.fetchone()
        id_user = str(result['id_user'])

        # Crear una nueva sesión y un perfil vacío para el usuario
        cursor.execute("INSERT INTO session (id_user) VALUES (%s)", (id_user,))
        cursor.execute("INSERT INTO profile (id_user) VALUES (%s)", (id_user,))
        db.commit()

        return {"status": "success", "id_user": id_user}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# Endpoint para servir el frontend
@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

# Endpoint para crear/actualizar el perfil del usuario (sin manejar el proyecto)
@app.post("/v1/profile")
async def create_profile(profile: ProfileModel):
    try:
        # Verificar si el perfil ya existe
        cursor.execute("SELECT * FROM profile WHERE id_user = %s", (profile.id_user,))
        existing_profile = cursor.fetchone()

        if existing_profile:
            # Actualizar los campos del perfil
            cursor.execute("""
                UPDATE profile
                SET position = %s, department = %s, sector = %s
                WHERE id_user = %s
            """, (profile.position, profile.department, profile.sector, profile.id_user))
        else:
            # Insertar un nuevo perfil
            cursor.execute("""
                INSERT INTO profile (id_user, position, department, sector)
                VALUES (%s, %s, %s, %s)
            """, (profile.id_user, profile.position, profile.department, profile.sector))
        db.commit()

        return {"message": "Profile updated successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# Endpoint para agregar un nuevo proyecto
@app.post("/v1/project")
async def add_project(project_req: ProjectRequest):
    try:
        cursor.execute("INSERT INTO project (id_user, project) VALUES (%s, %s)", 
                       (project_req.id_user, project_req.project))
        db.commit()
        project_id = cursor.lastrowid
        return {"message": "Project added successfully", "id_project": project_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# Endpoint para generar la pregunta basada en el perfil y el último proyecto agregado
@app.post("/v1/generate-question")
def generate_question(req: QuestionRequest):
    id_user = req.id_user

    try:
        # Se asume que la tabla question se ha modificado para incluir la columna id_project
        cursor.execute("""
            SELECT p.position, p.department, p.sector, pr.project, pr.id_project
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

        # Obtener el id de la sesión actual para el usuario
        cursor.execute("SELECT id FROM session WHERE id_user = %s ORDER BY date DESC LIMIT 1", (id_user,))
        session_data = cursor.fetchone()
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found for user")
        session_id = session_data["id"]

        # Guardar la pregunta en la tabla question incluyendo el id_project
        cursor.execute("INSERT INTO question (id, question, id_project) VALUES (%s, %s, %s)",
                       (session_id, prompt, profile_data['id_project']))
        db.commit()

        return {"status": "success", "question": prompt}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

# Endpoint para enviar la pregunta al LLM y almacenar la respuesta
@app.post("/v1/ask")
def ask_mistral(req: QuestionRequest):
    id_user = req.id_user

    try:
        # Obtener el id de la sesión actual para el usuario
        cursor.execute("SELECT id FROM session WHERE id_user = %s ORDER BY date DESC LIMIT 1", (id_user,))
        session_data = cursor.fetchone()
        if not session_data:
            raise HTTPException(status_code=404, detail="Session not found for user")
        session_id = session_data["id"]

        # Obtener la última pregunta registrada para la sesión
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

        # Guardar la respuesta en la tabla answer
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

