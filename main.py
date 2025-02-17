from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List
from pydantic import BaseModel
import uuid
import uvicorn
from datetime import datetime
import logging
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('game_server.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define the settings model
class GameSettings(BaseModel):
    version: str
    draftMode: str
    matchFormat: str
    playerCount: str
    timeLimit: str

# Updated room storage with settings
rooms: Dict[str, Dict[str, any]] = {}

@app.post("/create-room")
async def create_room(request: Request):
    """Create a new room with game settings"""
    settings_data = await request.json()
    # logger.info(settings_data)
    
    try:
        settings = GameSettings(**settings_data)
    except Exception as e:
        logger.error(f"Invalid settings data: {e}")
        return {"error": str(e)}, 400
    
    room_id = str(uuid.uuid4())[:8]
    rooms[room_id] = {
        "bans": [],
        "picks": [],
        "settings": settings.model_dump(),  # Updated from dict()
        "status": "waiting"
    }
    logger.info(f"New room created - ID: {room_id}, Settings: {settings.model_dump()}")  # Updated from dict()
    return {"room_id": room_id}

@app.websocket("/ws/draft")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    query_params = websocket.query_params
    room_id = query_params.get("id")

    if not room_id or room_id not in rooms:
        logger.warning(f"Invalid room connection attempt - ID: {room_id}")
        await websocket.close()
        return

    logger.info(f"New client connected to room {room_id}")

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            champion = data.get("champion")

            if action == "ban":
                rooms[room_id]["bans"].append(champion)
                logger.info(f"Room {room_id}: Champion {champion} banned")
            elif action == "pick":
                rooms[room_id]["picks"].append(champion)
                logger.info(f"Room {room_id}: Champion {champion} picked")

            await websocket.send_json(rooms[room_id])

    except WebSocketDisconnect:
        logger.info(f"Client disconnected from room {room_id}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
