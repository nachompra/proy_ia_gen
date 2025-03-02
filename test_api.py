import pytest
from fastapi.testclient import TestClient
from main import app # Asumiendo que tu aplicación se guarda en "api.py"
import mistralai
from mistralai.client import MistralClient
from pydantic import BaseModel
from typing import List

client = TestClient(app)

# Test para el endpoint que genera el usuario y crea sesión y perfil vacío
def test_get_user():
    response = client.get("/api/user")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"
    # Se espera que devuelva un id_user (en formato string o convertible a int)
    assert "id_user" in data

# Test para crear o actualizar un perfil
def test_create_profile():
    # Primero obtenemos un id de usuario
    response = client.get("/api/user")
    user_id = int(response.json()["id_user"])
    
    profile_data = {
        "id_user": user_id,
        "position": "Manager",
        "department": "Sales",
        "sector": "Retail",
    }
    response = client.post("/v1/profile", json=profile_data)
    assert response.status_code == 200
    data = response.json()
    assert "Profile updated successfully" in data.get("message", "")

# Test para agregar un nuevo proyecto
def test_add_project():
    response = client.get("/api/user")
    user_id = int(response.json()["id_user"])
    
    project_data = {
        "id_user": user_id,
        "project": "Project B"
    }
    response = client.post("/v1/project", json=project_data)
    assert response.status_code == 200
    data = response.json()
    assert data.get("message") == "Project added successfully"
    assert "id_project" in data

# Test para generar la pregunta (prompt) a partir del perfil y proyecto
def test_generate_question():
    response = client.get("/api/user")
    user_id = int(response.json()["id_user"])
    
    # Crear perfil y proyecto para el usuario
    profile_data = {
        "id_user": user_id,
        "position": "Analyst",
        "department": "Operations",
        "sector": "Logistics",
        "project": "Project C"
    }
    # Actualizar perfil
    client.post("/v1/profile", json=profile_data)
    # Agregar proyecto
    client.post("/v1/project", json={"id_user": user_id, "project": "Project C"})
    
    response = client.post("/v1/generate-question", json={"id_user": user_id, "question": ""})
    assert response.status_code == 200
    data = response.json()
    assert "question" in data
    # Comprobamos que el prompt generado contenga palabras clave (por ejemplo, "KPIs")
    assert "KPIs" in data["question"]

from fastapi.testclient import TestClient
from main import app  # Import your FastAPI app
from pydantic import BaseModel
from typing import List
import json

client = TestClient(app)

def test_ask_mistral(monkeypatch):
    # Setup: Create user and profile
    response = client.get("/api/user")
    user_id = response.json()["id_user"]
    
    profile_data = {
        "id_user": user_id,
        "position": "Analyst",
        "department": "Operations",
        "sector": "Logistics"
    }
    client.post("/v1/profile", json=profile_data)
    client.post("/v1/project", json={"id_user": user_id, "project": "Project D"})
    client.post("/v1/generate-question", json={"id_user": user_id, "question": ""})

    # Mock LangChain components
    class MockKPI(BaseModel):
        name: str = "Test KPI"
        formula: str = "SUM(test)/total"
        description: str = "Test KPI description"

    class MockKPIList(BaseModel):
        kpis: List[MockKPI] = [MockKPI()]
        summary: str = "Test summary of KPIs"

    class MockChain:
        def invoke(self, *args, **kwargs):
            return MockKPIList()

    # Enhanced database mock
def mock_db_execute(self, query, params=None):
    # Session ID query
    if "SELECT id FROM session" in query:
        return [{"id": 123}]
    
    # Profile+project context query
    if "FROM profile p JOIN project pr" in query:
        return [{
            "position": "Analyst",
            "department": "Operations",
            "sector": "Logistics",
            "project": "Project D",
            "id_project": 1  # Added missing field
        }]
    
    # Question query
    if "FROM question" in query:
        return [{
            "id_question": 1, 
            "question": "test question",
            "id": 123  # Match session ID
        }]
    
    # User ID query
    if "FLOOR(RAND()" in query:
        return [{"id_user": 456}]
    
    # All other SELECTs return comprehensive dummy data
    if "SELECT" in query:
        return [{
            "id": 123,
            "id_user": 456,
            "position": "Analyst",
            "department": "Operations",
            "sector": "Logistics",
            "project": "Project D",
            "id_question": 1,
            "question": "test",
            "id_project": 1
        }]
    
    return True

    def mock_db_commit():
        return True

    # Apply patches
    monkeypatch.setattr("main.chain", MockChain())
    monkeypatch.setattr("pymysql.cursors.Cursor.execute", mock_db_execute)
    monkeypatch.setattr("pymysql.connections.Connection.commit", mock_db_commit)

    # Execute test request
    response = client.post("/v1/ask", json={"id_user": user_id, "question": "Generate KPIs"})
    
    # Verify response
    assert response.status_code == 200, f"Unexpected status code. Response: {response.text}"
    data = response.json()
    assert "kpis" in data, "Missing kpis field in response"
    assert "summary" in data, "Missing summary field in response"
    assert len(data["kpis"]) > 0, "No KPIs returned"