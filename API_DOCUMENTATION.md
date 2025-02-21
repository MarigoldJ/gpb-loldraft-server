# GPB LoL Draft Server API Documentation

## Base URL

```
http://localhost:8000
```

## Models

### PlayerCountType (Enum)

- `solo`
- `representative`
- `team`

### GameSettings

```json
{
  "version": "string",
  "draftMode": "string",
  "matchFormat": "string",
  "playerCount": "PlayerCountType",
  "timeLimit": "string"
}
```

### GameResult

```json
{
  "winner": "string", // "team1" or "team2"
  "score": {
    "team1": "number",
    "team2": "number"
  }
}
```

### LobbyUser

```json
{
  "id": "string",
  "nickname": "string",
  "team": "string", // "BLUE" | "RED" | "SPECTATOR"
  "position": "number",
  "isReady": "boolean",
  "isHost": "boolean"
}
```

### LobbyStatus

```json
{
  "gameCode": "string",
  "settings": "GameSettings",
  "users": "LobbyUser[]",
  "status": "string", // "waiting" | "ready" | "in_progress" | "completed"
  "currentSet": "number",
  "allReady": "boolean"
}
```

## REST Endpoints

### Create Room

- **POST** `/create-room`
- **Request Body**: GameSettings
- **Response**:

```json
{
  "room_id": "string"
}
```

- **Error Response** (400):

```json
{
  "detail": "string"
}
```

### Get Game Information

- **GET** `/game/{game_code}`
- **Response** (200): Room information including bans, picks, settings, and users
- **Error Response** (404):

```json
{
  "detail": "Room not found"
}
```

### Get Lobby Status

- **GET** `/game/{game_code}/status`
- **Response** (200): LobbyStatus
- **Error Response** (404):

```json
{
  "detail": "Room not found"
}
```

### Submit Game Result

- **POST** `/game/{game_code}/result`
- **Request Body**: GameResult
- **Response** (200):

```json
{
  "status": "string",
  "currentSet": "number"
}
```

- **Error Response** (404):

```json
{
  "detail": "Room not found"
}
```

### Join Lobby

- **POST** `/game/{game_code}/join`
- **Request Body**:

```json
{
  "nickname": "string"
}
```

- **Response**: LobbyUser

### Update Team

- **PATCH** `/game/{game_code}/user/{user_id}/team`
- **Request Body**:

```json
{
  "team": "string", // "BLUE" | "RED" | "SPECTATOR"
  "position": "number"
}
```

- **Response**: Updated LobbyUser

### Update Ready Status

- **PATCH** `/game/{game_code}/user/{user_id}/ready`
- **Request Body**:

```json
{
  "isReady": "boolean"
}
```

- **Response**: Updated LobbyUser

## WebSocket Endpoint

### Draft Connection

- **Protocol**: `WebSocket`
- **Base URL**: `ws://localhost:8000`
- **Path**: `/ws/draft` (Important: The full path must include "/ws/")
- **Full URL**: `ws://localhost:8000/ws/draft`
- **Connection Example**:

```javascript
// JavaScript WebSocket connection example

// Correct way - include '/ws/' in the path
const ws = new WebSocket(
  `ws://localhost:8000/ws/draft?id=${gameCode}&spectator=false`
);

// Wrong way - missing '/ws/' prefix
// const ws = new WebSocket(`ws://localhost:8000/draft?id=${gameCode}&spectator=false`); // This will not work!
```

- **Query Parameters**:

  - `id`: Room ID (required)
  - `spectator`: Boolean (optional, default: false)

- **Important Notes**:
  1. This is a WebSocket endpoint that requires the `ws://` or `wss://` protocol
  2. The path MUST include `/ws/` prefix (`/ws/draft`)
  3. Common mistakes to avoid:
     - Missing the `/ws/` prefix in the URL path
     - Using `http://` or `https://` instead of `ws://`
     - Using `fetch()` or `axios` (these are for HTTP requests)
     - Trying to access the endpoint directly in a browser

### WebSocket Messages

#### Client -> Server

```json
{
  "action": "string", // "ban" | "pick" | "submit_result" | "update_team" | "update_ready"
  "champion": "string", // Required for ban/pick actions
  "result": "GameResult", // Required for submit_result action
  "userId": "string", // Required for update_team/ready actions
  "teamData": {
    // Required for update_team action
    "team": "string",
    "position": "number"
  },
  "isReady": "boolean" // Required for update_ready action
}
```

#### Server -> Client

- Regular room updates

```json
{
  "bans": ["string"],
  "picks": ["string"],
  "settings": {
    "version": "string",
    "draftMode": "string",
    "matchFormat": "string",
    "playerCount": "string",
    "timeLimit": "string"
  },
  "status": "string",
  "participants": {
    "string": {
      "connected_at": "string",
      "client_id": "string"
    }
  },
  "spectators": {
    "string": {
      "connected_at": "string",
      "client_id": "string"
    }
  },
  "currentSet": "number",
  "results": ["GameResult"],
  "users": ["LobbyUser"]
}
```

- Status updates

```json
{
  "type": "status_update",
  "data": {
    "gameCode": "string",
    "settings": {
      "version": "string",
      "draftMode": "string",
      "matchFormat": "string",
      "playerCount": "string",
      "timeLimit": "string"
    },
    "users": [
      {
        "id": "string",
        "nickname": "string",
        "team": "string",
        "position": "number",
        "isReady": "boolean",
        "isHost": "boolean"
      }
    ],
    "status": "string",
    "currentSet": "number",
    "allReady": "boolean"
  }
}
```

## Participant Limits

- Solo: 1 participant
- Representative: 2 participants
- Team: 10 participants
