import os
import time
import json
import uuid
import tempfile
import requests
import shutil
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import subprocess
import wave

# Import piper library
try:
    from piper.voice import PiperVoice
except ImportError:
    PiperVoice = None

from voices.profiles import VOICE_PROFILES
from voices.config import DEFAULT_MODEL, MAX_TEXT_LENGTH, CORS_ORIGINS

app = FastAPI(title="VoxAI API", version="1.0.0")

# Request counting for health endpoint
REQUESTS_TODAY = 0
START_TIME = time.time()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if "*" not in CORS_ORIGINS else ["*"],
    allow_credentials=True if "*" not in CORS_ORIGINS else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "Charon"
    speed: Optional[float] = None
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

def ensure_model(model_name: str):
    os.makedirs("models", exist_ok=True)
    onnx_path = f"models/{model_name}.onnx"
    config_path = f"models/{model_name}.onnx.json"
    
    if not os.path.exists(onnx_path):
        print(f"Downloading model {model_name} from HuggingFace...")
        # Piper models repository URL (pt_BR-faber-medium is standard)
        base_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/faber/medium/"
        
        try:
            r = requests.get(f"{base_url}pt_BR-faber-medium.onnx", stream=True, timeout=30)
            r.raise_for_status()
            with open(onnx_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            r = requests.get(f"{base_url}pt_BR-faber-medium.onnx.json", stream=True, timeout=10)
            r.raise_for_status()
            with open(config_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Model {model_name} downloaded successfully.")
        except Exception as e:
            print(f"Failed to download model {model_name}: {e}")
            if os.path.exists(onnx_path): os.remove(onnx_path)
            if os.path.exists(config_path): os.remove(config_path)
            return False
    return True

def run_piper(text: str, voice_profile: dict, output_path: str):
    model_name = voice_profile.get("model", DEFAULT_MODEL)
    
    if not ensure_model(model_name):
        return False
        
    try:
        model_path = f"models/{model_name}.onnx"
        config_path = f"models/{model_name}.onnx.json"
        speed = voice_profile.get("speed", 1.0)
        
        # Diagnostics
        print(f"Synthesizing: '{text[:50]}...' with {model_name} at speed {speed}")

        # Try to use Piper library directly first (more robust on many hosts)
        if PiperVoice:
            try:
                print("Using Piper Python library directly...")
                voice = PiperVoice.load(model_path, config_path)
                
                # length_scale is inverse of speed
                voice.length_scale = 1.0 / speed
                
                with wave.open(output_path, "wb") as wav_file:
                    voice.synthesize(text, wav_file)
                
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    print(f"Successfully generated audio via library at {output_path}")
                    return True
            except Exception as lib_err:
                print(f"Library synthesis failed: {lib_err}. Falling back to CLI...")

        # Fallback to CLI
        piper_binary = shutil.which("piper") or shutil.which("piper-tts")
        
        if not piper_binary:
            # Try some common locations if which fails
            common_paths = [
                "/usr/local/bin/piper",
                "/usr/bin/piper",
                os.path.expanduser("~/.local/bin/piper"),
                os.path.expanduser("~/.local/bin/piper-tts")
            ]
            for p in common_paths:
                if os.path.exists(p):
                    piper_binary = p
                    break
        
        if not piper_binary:
            print("ERROR: Piper binary not found in PATH or common locations.")
            return False

        print(f"Using piper binary: {piper_binary}")
        
        cmd = [
            piper_binary,
            "--model", model_path,
            "--output_file", output_path,
            "--length_scale", str(1.0 / speed)
        ]
        
        process = subprocess.Popen(
            cmd, 
            stdin=subprocess.PIPE, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True
        )
        stdout, stderr = process.communicate(input=text)
        
        if process.returncode != 0:
            print(f"Piper execution failed (code {process.returncode}): {stderr}")
            return False
            
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"Critical error in run_piper: {e}")
        return False

@app.post("/synthesize")
async def synthesize(request: SynthesizeRequest):
    global REQUESTS_TODAY
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
    
    # Use requested parameters or profile defaults
    # Speed in request overrides profile speed if provided
    speed = request.speed if request.speed is not None else profile.get("speed", 1.0)
    
    # We pass a modified profile for the run
    run_profile = profile.copy()
    run_profile["speed"] = speed
    
    success = run_piper(request.text, run_profile, output_path)
    
    if not success or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise HTTPException(status_code=500, detail="Erro na síntese. Verifique se o Piper está instalado e o modelo foi baixado corretamente.")

    return FileResponse(
        output_path, 
        media_type="audio/wav", 
        filename="voxai.wav"
    )

@app.post("/synthesize/stream")
async def synthesize_stream(request: SynthesizeRequest):
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Texto não pode estar vazio")
    
    if request.voice not in VOICE_PROFILES:
        raise HTTPException(status_code=400, detail="Voz não encontrada")
    
    profile = VOICE_PROFILES[request.voice]
    model_name = profile.get("model", DEFAULT_MODEL)
    model_path = f"models/{model_name}.onnx"
    
    if not ensure_model(model_name):
        raise HTTPException(status_code=500, detail="Falha ao carregar modelo de voz")

    def generate():
        # Try both 'piper' and 'piper-tts'
        commands = ["piper", "piper-tts"]
        process = None
        cmd_used = None
        
        speed = request.speed if request.speed != 1.0 else profile.get("speed", 1.0)
        
        for base_cmd in commands:
            try:
                cmd = [
                    base_cmd,
                    "--model", model_path,
                    "--output_raw",
                    "--length_scale", str(1.0 / speed)
                ]
                process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                cmd_used = base_cmd
                break
            except FileNotFoundError:
                continue
        
        if not process:
            yield b"Error: Piper not found"
            return
            
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
        "requests_today": REQUESTS_TODAY,
        "piper_available": any(os.system(f"which {cmd} > /dev/null 2>&1") == 0 for cmd in ["piper", "piper-tts"])
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
