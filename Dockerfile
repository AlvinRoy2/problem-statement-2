# Stage 1: Build the frontend (Vite/React)
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build

# Stage 2: Serve the backend + frontend (FastAPI)
FROM python:3.11-slim
WORKDIR /app

# Install backend dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and backend files
COPY . .

# Copy built frontend assets from Stage 1 into the python target directory
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Expose port (Cloud Run defaults to 8080 or provides $PORT)
EXPOSE 8080

# Cloud run command
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
