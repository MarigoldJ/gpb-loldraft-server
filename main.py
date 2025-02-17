from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
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

# CORS configuration
origins = [
    "http://localhost:3000",     # Next.js dev server
    "http://localhost:8000",     # FastAPI dev server
    "https://your-production-domain.com"  # Replace with your production domain
]

# Add CORS middleware with specific configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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

@app.get("/game/{game_code}")
async def get_game(game_code: str):
    """Get game information for a specific room"""
    if game_code not in rooms:
        logger.warning(f"Room not found - ID: {game_code}")
        raise HTTPException(status_code=404, detail="Room not found")
    
    logger.info(f"Room info requested - ID: {game_code}")
    return rooms[game_code]

@app.websocket("/ws/draft")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    query_params = websocket.query_params
    room_id = query_params.get("id")
    client_id = str(uuid.uuid4())[:6]  # Generate unique client ID

    if not room_id or room_id not in rooms:
        logger.warning(f"Invalid room connection attempt - Client: {client_id}, Room: {room_id}")
        await websocket.close()
        return

    # Initialize connected_clients if not exists
    if "connected_clients" not in rooms[room_id]:
        rooms[room_id]["connected_clients"] = {}
    
    # Add client to room
    rooms[room_id]["connected_clients"][client_id] = {
        "connected_at": datetime.now().isoformat(),
        "client_id": client_id
    }
    
    logger.info(f"Client {client_id} connected to room {room_id} - Active clients: {len(rooms[room_id]['connected_clients'])}")

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            champion = data.get("champion")

            if action == "ban":
                rooms[room_id]["bans"].append(champion)
                logger.info(f"Room {room_id}: Champion {champion} banned by client {client_id}")
            elif action == "pick":
                rooms[room_id]["picks"].append(champion)
                logger.info(f"Room {room_id}: Champion {champion} picked by client {client_id}")

            await websocket.send_json(rooms[room_id])

    except WebSocketDisconnect:
        # Remove client from room
        if client_id in rooms[room_id]["connected_clients"]:
            del rooms[room_id]["connected_clients"][client_id]
            logger.info(f"Client {client_id} disconnected from room {room_id} - Remaining clients: {len(rooms[room_id]['connected_clients'])}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
