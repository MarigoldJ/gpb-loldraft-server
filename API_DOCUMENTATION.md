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

## Implementation Notes

### State Management

- 서버는 모든 게임 방의 상태를 메모리에 저장
- 각 방은 고유한 8자리 ID로 식별
- WebSocket 연결은 별도로 관리되어 실시간 업데이트 제공

### Game Modes

- Solo: 혼자서 연습하는 모드 (WebSocket 미지원)
- Representative: 팀 대표 참가 모드
- Team: 팀 전체 참가 모드

### Room Lifecycle

1. 방 생성: 설정 검증 후 고유 ID 할당
2. 사용자 참가: 닉네임으로 참가, 첫 참가자가 방장
3. 팀 구성: 블루팀/레드팀/관전자로 역할 분배
4. 게임 진행: 모든 참가자 준비 완료 시 시작
5. 결과 제출: 게임 종료 후 결과 등록

### Real-time Updates

- 방의 모든 상태 변경은 실시간으로 전체 참가자에게 전달
- WebSocket을 통한 양방향 통신으로 즉각적인 상태 동기화
