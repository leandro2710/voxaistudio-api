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
    
    if not os.path.exists(onnx_path) or not os.path.exists(config_path):
        print(f"Downloading model {model_name} from HuggingFace...")
        parts = model_name.split("-")
        if len(parts) < 3:
            return False, f"Formato de nome de modelo inválido: {model_name}"
            
        voice_name = parts[1] 
        quality = parts[2] 
        
        base_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/pt/pt_BR/{voice_name}/{quality}/"
        
        try:
            # Download ONNX
            r = requests.get(f"{base_url}{model_name}.onnx", stream=True, timeout=60)
            if r.status_code != 200:
                return False, f"Falha ao baixar ONNX (Status {r.status_code})"
            with open(onnx_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Download Config
            r = requests.get(f"{base_url}{model_name}.onnx.json", stream=True, timeout=20)
            if r.status_code != 200:
                return False, f"Falha ao baixar JSON (Status {r.status_code})"
            with open(config_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Model {model_name} downloaded successfully.")
        except Exception as e:
            if os.path.exists(onnx_path): os.remove(onnx_path)
            if os.path.exists(config_path): os.remove(config_path)
            return False, f"Erro no download: {str(e)}"
    return True, None

def run_piper(text: str, voice_profile: dict, output_path: str):
    model_name = voice_profile.get("model", DEFAULT_MODEL)
    
    success, error = ensure_model(model_name)
    if not success:
        return False, error
        
    try:
        model_path = f"models/{model_name}.onnx"
        config_path = f"models/{model_name}.onnx.json"
        speed = voice_profile.get("speed", 1.0)
        
        # Piper noise parameters for more natural sound
        stability = voice_profile.get("stability", 0.5)
        noise_scale = 1.0 - (stability * 0.8) 
        
        expressiveness = voice_profile.get("expressiveness", 0.6)
        noise_w = 0.2 + (expressiveness * 0.8) 

        # Diagnostics
        print(f"Synthesizing with {model_name}: speed={speed}, noise_scale={noise_scale:.2f}, noise_w={noise_w:.2f}")

        # Try to use Piper library directly first
        if PiperVoice:
            try:
                voice = PiperVoice.load(model_path, config_path)
                voice.length_scale = 1.0 / speed
                voice.noise_scale = noise_scale
                voice.noise_w = noise_w
                
                with wave.open(output_path, "wb") as wav_file:
                    voice.synthesize(text, wav_file)
                
                if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    return True, None
            except Exception as lib_err:
                print(f"Library synthesis failed: {lib_err}")

        # Fallback to CLI
        piper_binary = shutil.which("piper") or shutil.which("piper-tts")
        if not piper_binary:
            for p in ["/usr/local/bin/piper", "/usr/bin/piper", "/usr/bin/piper-tts"]:
                if os.path.exists(p): piper_binary = p; break
        
        if piper_binary:
            cmd = [
                piper_binary,
                "--model", model_path,
                "--output_file", output_path,
                "--length_scale", str(1.0 / speed),
                "--noise_scale", str(noise_scale),
                "--noise_w", str(noise_w)
            ]
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate(input=text)
            if process.returncode != 0:
                print(f"CLI fail: {stderr}")
                return False, f"CLI error: {stderr[:100]}"
            
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return True, None
            
        return False, "Piper não produziu áudio ou binário não encontrado"
    except Exception as e:
        print(f"Synthesis error: {e}")
        return False, f"Exceção: {str(e)}"

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
    
    # Blend request parameters with profile defaults
    run_profile = profile.copy()
    if request.speed is not None: run_profile["speed"] = request.speed
    else: run_profile["speed"] = profile.get("speed", 1.0)
    
    # Map high-level stability/expressiveness to Piper params
    run_profile["stability"] = request.stability
    run_profile["expressiveness"] = request.expressiveness
    
    success, error_detail = run_piper(request.text, run_profile, output_path)
    
    if not success or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        error_msg = f"Erro na síntese: {error_detail}" if error_detail else "Erro na síntese. Verifique se o Piper está instalado e o modelo foi baixado corretamente."
        print(f"Synthesis failed: {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)

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
    
    success, _ = ensure_model(model_name)
    if not success:
        raise HTTPException(status_code=500, detail="Falha ao carregar modelo de voz")

    def generate():
        # Try both 'piper' and 'piper-tts'
        commands = ["piper", "piper-tts"]
        process = None
        cmd_used = None
        
        speed = request.speed if request.speed is not None else profile.get("speed", 1.0)
        
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
