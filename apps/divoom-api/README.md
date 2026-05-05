# Divoom HTTP API

This application provides a simple HTTP server to control your Divoom MiniToo from any device or application.

## Prerequisites

- **Python 3.8+**
- **Flask** (`pip install flask`)
- The core toolkit must be functional (see root `README.md`).

## Running the Server

```bash
cd apps/divoom-api
python server.py
```

By default, the server runs on `http://localhost:5000`.

## API Endpoints

### 1. Check Status
`GET /status`

### 2. Display Scrolling Text
`POST /text`
```json
{
  "text": "Hello Gemini!",
  "color": "00FF00"
}
```

### 3. Switch Face
`POST /face`
```json
{
  "id": 1
}
```

### 4. Set Brightness
`POST /brightness`
```json
{
  "level": 50
}
```

### 5. Custom JSON Command
`POST /json`
```json
{
  "Command": "Channel/SetClockSelectId",
  "ClockId": 32000,
  "DeviceId": 12345
}
```

## Examples with CURL

```bash
# Set brightness to 80%
curl -X POST http://localhost:5000/brightness -H "Content-Type: application/json" -d '{"level": 80}'

# Display green text
curl -X POST http://localhost:5000/text -H "Content-Type: application/json" -d '{"text": "API Working!", "color": "00FF00"}'
```
