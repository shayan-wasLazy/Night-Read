FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app.py ./app.py
COPY --from=web /web/dist /frontend
RUN useradd --create-home --uid 10001 nightread && mkdir -p /data/Books /appdata && chown -R nightread:nightread /data /appdata
USER nightread
EXPOSE 8080
CMD ["uvicorn","app:app","--host","0.0.0.0","--port","8080"]