# VoxAI API 🎙️

API REST de alto desempenho para síntese de voz (TTS) em Português Brasileiro, alimentada pelo **Piper TTS**.

Esta API foi desenvolvida para ser o motor de voz do **VoxAI Studio**, oferecendo uma alternativa 100% gratuita, privada e offline (após o download inicial) ao Gemini TTS.

## 🚀 Como fazer Deploy no Render.com

1.  Crie uma conta gratuita em [Render.com](https://render.com).
2.  Crie um novo **Web Service**.
3.  Conecte o repositório contendo a pasta `voxai-api`.
4.  O Render detectará o arquivo `render.yaml` (ou você pode configurar manualmente):
    *   **Runtime**: Python
    *   **Build Command**: `pip install -r requirements.txt`
    *   **Start Command**: `uvicorn main:app --host 0.0.0.0 --port 8000`
5.  Clique em **Deploy**.

**Nota**: No plano free do Render, a API pode levar alguns segundos para "acordar" após períodos de inatividade. O primeiro uso também levará cerca de 30 segundos para baixar o modelo `pt_BR-faber-medium`.

## 🛠️ Endpoints

### `GET /`
Verifica se a API está online e lista as vozes disponíveis.

### `GET /voices`
Retorna a lista completa de perfis de voz detalhados.

### `POST /synthesize`
Gera um arquivo `.wav` a partir do texto.

**Exemplo de Payload:**
```json
{
  "text": "Olá, eu sou o VoxAI. Como posso te ajudar hoje?",
  "voice": "Charon",
  "speed": 1.0,
  "style": "Narrativo",
  "tone": "Neutro"
}
```

**Exemplo curl:**
```bash
curl -X POST "https://voxai-api.onrender.com/synthesize" \
     -H "Content-Type: application/json" \
     -d '{"text": "Teste de voz", "voice": "Titan"}' \
     --output narra.wav
```

### `POST /synthesize/stream`
Retorna o áudio em formato stream para reprodução instantânea.

## 🎙️ Vozes Disponíveis

### Padrão
*   **Charon**: Grave e formal
*   **Aurora**: Suave e feminina
*   **Titan**: Forte e marcante
*   **Lyra**: Animada e jovem

### Especiais
*   **O Craque**: Alta energia (Futebol)
*   **O Sábio**: Lento e profundo
*   **O Vilão**: Frio e calculista
*   **A Narradora**: Elegante (Documentário)

## 📦 Testando Localmente

1.  Certifique-se de ter o Python 3.11+ instalado.
2.  Instale o piper-tts: `pip install piper-tts`
3.  Instale as dependências: `pip install -r requirements.txt`
4.  Rode o servidor: `python main.py`
5.  Acesse `http://localhost:8000/docs` para ver a documentação interativa (Swagger).

---
Desenvolvido para o ecossistema **VoxAI Studio**.
