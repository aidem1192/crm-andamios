import uvicorn
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

if __name__ == "__main__":
    # Railway (y otras plataformas) inyectan el puerto real via la variable de entorno PORT.
    # En local, si no está definida, se usa 8000 como siempre.
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    uvicorn.run("app.main:app", host=host, port=port, reload=False, workers=1)
