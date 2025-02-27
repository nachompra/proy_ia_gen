from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import List
import os
from mistralai import Mistral
from dotenv import load_dotenv
import pymysql
import sqlalchemy
from datetime import datetime

app = FastAPI()

# LOAD ALL THE INFORMATION THAT THE APP WILL REQUIRE
load_dotenv()
api_key = os.getenv("MISTRAL_API_KEY")
model = "mistral-small-2402"
username = os.getenv("DB_USER")
password = os.getenv("DB_PW")
host = os.getenv("DB_HOST")
port = 3306


#DB CONNECTION
db = pymysql.connect(host = host,
                     user = username,
                     password = password,
                     cursorclass = pymysql.cursors.DictCursor
)

# CURSOR OBJECT WILL EXECUTE ALL THE QUERIES AND FETCH THE DATA
cursor = db.cursor()

# USE CORRECT TABLE
cursor.connection.commit()
use_db = ''' USE kpi_database'''
cursor.execute(use_db)


# API

@app.get("/")
def home():
    return {"message": "API en pie y danzando"}

class QuestionRequest(BaseModel):
    question: str

@app.post("/v1/ask")
def ask_mistral(req: QuestionRequest):
    client = Mistral(api_key)
    chat_response = client.chat.complete(
        model=model,
        messages=[
            {"role": "user", "content": req.question}
        ]
    )
    prompt = req.question
    answer =  chat_response.choices[0].message.content
    insert_data = '''
    INSERT INTO session (prompt, answer) 
    VALUES (%s, %s)
    '''
    cursor.execute(insert_data, (prompt, answer))
    db.commit()
    return {"message": answer}

class Session(BaseModel):
    id: int
    prompt: str
    answer: str
    date: datetime
    

@app.get("/v1/db", response_model=List[Session])
async def get_sessions():
    try:
        sql = '''SELECT * FROM session'''
        cursor.execute(sql)
        my_list = cursor.fetchall()
        if not my_list:
            raise HTTPException(status_code=404, detail="No sessions found")
        return my_list
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error querying the database: {str(e)}")