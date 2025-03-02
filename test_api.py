import pytest
from fastapi.testclient import TestClient
from main import app # Asumiendo que tu aplicación se guarda en "api.py"
import mistralai
from mistralai.client import MistralClient

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

def test_ask_mistral(monkeypatch):
    # Get user ID
    response = client.get("/api/user")
    user_id = int(response.json()["id_user"])
    
    # Create profile and project
    profile_data = {
        "id_user": user_id,
        "position": "Analyst",
        "department": "Operations",
        "sector": "Logistics",
        "project": "Project D"
    }
    client.post("/v1/profile", json=profile_data)
    client.post("/v1/project", json={"id_user": user_id, "project": "Project D"})
    client.post("/v1/generate-question", json={"id_user": user_id, "question": ""})
    
    # Mock Mistral Client Structure
    class MockMessage:
        def __init__(self):
            self.content = "1. **Test KPI**: Dummy formula"

    class MockChoice:
        def __init__(self):
            self.message = MockMessage()

    class MockChat:
        def create(self, *args, **kwargs):
            response = type("Response", (), {"choices": [MockChoice()]})
            return response

    class MockMistralClient:
        def __init__(self, *args, **kwargs):
            self.chat = MockChat()  # Attach the chat.create method

    # Replace the real client with our mock
    monkeypatch.setattr("mistralai.client.MistralClient", MockMistralClient)
    
    # Test the endpoint
    response = client.post("/v1/ask", json={"id_user": user_id, "question": "Generate KPIs"})
    
    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "KPI" in data["message"]