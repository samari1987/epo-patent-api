from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from requests.auth import HTTPBasicAuth
import os

app = FastAPI(title="EPO Patent Search API", version="1.0")

CONSUMER_KEY = os.getenv("CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")

class SearchRequest(BaseModel):
    query: str

def get_access_token():
    auth_url = "https://ops.epo.org/3.2/auth/accesstoken"
    response = requests.post(
        auth_url,
        auth=HTTPBasicAuth(CONSUMER_KEY, CONSUMER_SECRET),
        data={"grant_type": "client_credentials"},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to get EPO token")
    return response.json().get("access_token")

@app.get("/status")
def status():
    return {"status": "ok", "service": "EPO Patent Search"}

@app.post("/search")
def search_patents(request: SearchRequest):
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    url = f"https://ops.epo.org/3.2/rest-services/published-data/search?q=ti={request.query}"
    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="EPO API request failed")

    return {"query": request.query, "results": response.text}
