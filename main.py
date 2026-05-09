import os
import time
import json
import uuid
import tempfile
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import subprocess

from voices.profiles import VOICE_PROFILES
from voices.config import DEFAULT_MODEL, MAX_TEXT_LENGTH, CORS_ORIGINS

app = FastAPI(title="VoxAI API", version="1.0.0")

# Request counting for health endpoint
REQUESTS_TODAY = 0
START_TIME = time.time()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "Charon"
    speed: float = 1.0
    stability: float = 0.5
    clarity: float = 0.75
    expressiveness: float = 0.65
    style: str = "Narrativo"
    tone: str = "Neutro"

@app.middleware("http")
async def add_api_version_header(request: Request, call_next):
    global REQUESTS_TODAY
    REQUESTS_TODAY += 1
    response = await call_next(request)
    response.headers["X-API-Version"] = "1.0.0"
    return response

@app.get("/")
async def root():
    return {
        "status": "online",
        "version": "1.0.0",
        "name": "VoxAI API",
        "voices": list(VOICE_PROFILES.keys())
    }

@app.get("/voices")
async def get_voices():
    standard = [v for k, v in VOICE_PROFILES.items() if v["category"] == "Standard"]
    special = [v for k, v in VOICE_PROFILES.items() if v["category"] == "Special"]
    return {
        "standard": standard,
        "special": special
    }

def run_piper(text: str, voice_profile: dict, output_path: str):
    # This assumes piper is installed and in PATH
    # Command: echo "text" | piper --model model.onnx --output_file out.wav
    # We will use subprocess to run piper
    
    # In a real render deploy, we'd ensure the model is downloaded.
    # For now, we simulate the command structure.
    
    model_name = voice_profile.get("model", DEFAULT_MODEL)
    # Pitch and speed adjustments would be applied here if supported by the piper CLI
    # or by post-processing with ffmpeg.
    
    try:
        # Construct the command
        # Note: pt_BR-faber-medium should be in the models directory
        model_path = f"models/{model_name}.onnx"
        
        # Ensure models dir exists
        os.makedirs("models", exist_ok=True)
        
        # Simple piper command
        cmd = [
            "piper",
            "--model", model_path,
            "--output_file", output_path,
            "--length_scale", str(1.0 / voice_profile.get("speed", 1.0))
        ]
        
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate(input=text)
        
        if process.returncode != 0:
            print(f"Piper error: {stderr}")
            return False
        return True
    except Exception as e:
        print(f"Synthesis error: {e}")
        return False

@app.post("/synthesize")
async def synthesize(request: SynthesizeRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Texto não pode estar vazio")
    
    if len(request.text) > MAX_TEXT_LENGTH:
        raise HTTPException(status_code=400, detail=f"Máximo {MAX_TEXT_LENGTH} caracteres")
    
    if request.voice not in VOICE_PROFILES:
        raise HTTPException(status_code=400, detail="Voz não encontrada")
    
    profile = VOICE_PROFILES[request.voice]
    
    # Create temporary file
    temp_dir = tempfile.gettempdir()
    output_filename = f"voxai_{uuid.uuid4()}.wav"
    output_path = os.path.join(temp_dir, output_filename)
    
    success = run_piper(request.text, profile, output_path)
    
    if not success:
        # Fallback: if piper fails (e.g. model not found), we can't do much on Render FREE without setup
        # But according to instructions, it should download automatically.
        raise HTTPException(status_code=500, detail="Erro na síntese, tente novamente")

    return FileResponse(
        output_path, 
        media_type="audio/wav", 
        filename="voxai.wav",
        background=None # In a real app we'd want to delete the temp file after sending
    )

@app.post("/synthesize/stream")
async def synthesize_stream(request: SynthesizeRequest):
    # Similar to synthesize but for streaming
    # For Piper, we can stream the output of the process directly
    
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Texto não pode estar vazio")
    
    if request.voice not in VOICE_PROFILES:
        raise HTTPException(status_code=400, detail="Voz não encontrada")
    
    profile = VOICE_PROFILES[request.voice]
    model_name = profile.get("model", DEFAULT_MODEL)
    model_path = f"models/{model_name}.onnx"
    
    def generate():
        cmd = [
            "piper",
            "--model", model_path,
            "--output_raw",
            "--length_scale", str(1.0 / profile.get("speed", 1.0))
        ]
        
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # We need to send the text to stdin
        process.stdin.write(request.text.encode('utf-8'))
        process.stdin.close()
        
        while True:
            chunk = process.stdout.read(4096)
            if not chunk:
                break
            yield chunk
            
    return StreamingResponse(generate(), media_type="audio/wav")

@app.get("/health")
async def health():
    uptime = time.time() - START_TIME
    return {
        "status": "healthy",
        "uptime": int(uptime),
        "requests_today": REQUESTS_TODAY
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
