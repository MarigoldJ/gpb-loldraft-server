from enum import Enum
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

# Define player count types
class PlayerCountType(str, Enum):
    SOLO = "solo"
    REPRESENTATIVE = "representative"
    TEAM = "team"

# Define the settings model
class GameSettings(BaseModel):
    version: str
    draftMode: str
    matchFormat: str
    playerCount: PlayerCountType  # Updated to use enum
    timeLimit: str

# Participant limits per mode
PARTICIPANT_LIMITS = {
    PlayerCountType.SOLO: 1,
    PlayerCountType.REPRESENTATIVE: 2,
    PlayerCountType.TEAM: 10
}

# Updated room storage with settings
rooms: Dict[str, Dict[str, any]] = {}

@app.post("/create-room")
async def create_room(request: Request):
    """Create a new room with game settings"""
    settings_data = await request.json()
    
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
        "status": "waiting",
        "participants": {},  # Active game participants
        "spectators": {},    # Spectators
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
    is_spectator = query_params.get("spectator", "false").lower() == "true"
    client_id = str(uuid.uuid4())[:6]  # Generate unique client ID

    if not room_id or room_id not in rooms:
        logger.warning(f"Invalid room connection attempt - Client: {client_id}")
        await websocket.close()
        return

    room = rooms[room_id]
    player_count_type = room["settings"]["playerCount"]

    # Solo mode doesn't use WebSocket
    if player_count_type == PlayerCountType.SOLO:
        logger.warning(f"Solo mode doesn't support WebSocket connections")
        await websocket.close()
        return

    # Check participant limit if not spectator
    if not is_spectator:
        participant_limit = PARTICIPANT_LIMITS[player_count_type]
        if len(room["participants"]) >= participant_limit:
            logger.warning(f"Room {room_id} participant limit reached")
            await websocket.close()
            return
        room["participants"][client_id] = {
            "connected_at": datetime.now().isoformat(),
            "client_id": client_id
        }
    else:
        room["spectators"][client_id] = {
            "connected_at": datetime.now().isoformat(),
            "client_id": client_id
        }

    logger.info(f"Client {client_id} connected to room {room_id} as {'spectator' if is_spectator else 'participant'}")

    try:
        while True:
            data = await websocket.receive_json()
            # Only participants can perform actions
            if not is_spectator:
                action = data.get("action")
                champion = data.get("champion")

                if action == "ban":
                    room["bans"].append(champion)
                    logger.info(f"Room {room_id}: Champion {champion} banned by {client_id}")
                elif action == "pick":
                    room["picks"].append(champion)
                    logger.info(f"Room {room_id}: Champion {champion} picked by {client_id}")

            await websocket.send_json(room)

    except WebSocketDisconnect:
        if is_spectator:
            del room["spectators"][client_id]
        else:
            del room["participants"][client_id]
        logger.info(f"Client {client_id} disconnected from room {room_id} - Remaining clients: {len(rooms[room_id]['connected_clients'])}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
