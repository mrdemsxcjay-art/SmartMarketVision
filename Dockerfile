# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# SMART MARKET VISION - image unique : API + dashboard React dans un seul
# processus, un seul port (8000). Aucune execution d'ordre : l'application
# observe le marche et alerte, elle ne passe jamais d'ordre.
#
#   docker build -t smart-market-vision .
#   docker run --rm -p 8000:8000 --env-file .env -v "$PWD/data:/app/data" smart-market-vision
#
# Le fichier .env n'est JAMAIS copie dans l'image : il est fourni au lancement
# (--env-file ou variables d'environnement). Aucun secret ne doit entrer dans
# une couche d'image.
# ---------------------------------------------------------------------------

# --- etape 1 : construction du dashboard React (Node n'est utile qu'ici) ----
FROM node:20-alpine AS dashboard
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- etape 2 : runtime Python (FastAPI + uvicorn + Pillow) ------------------
FROM python:3.12-slim AS runtime

# ffmpeg/fonts : les captures de la Phase 7 ecrivent du texte dans le PNG.
# fonts-dejavu-core fournit exactement les polices utilisees et validees.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./

# l'API sert le dashboard depuis <racine>/frontend/dashboard_build
COPY --from=dashboard /build/frontend/dashboard_build /app/frontend/dashboard_build

# donnees persistantes : base SQLite + captures PNG reelles
RUN mkdir -p /app/data/captures
VOLUME ["/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python3 -c "import os,urllib.request,sys; port=os.environ.get('PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=4).status==200 else 1)"

# Le port d'écoute suit $PORT quand la plateforme l'impose (Render, Railway,
# Fly.io), et reste 8000 sinon (docker run -p 8000:8000, usage local).
CMD ["sh", "-c", "python3 -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
