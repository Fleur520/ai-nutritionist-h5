FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ARG VITE_DEFAULT_LOGIN_EMAIL=
ARG VITE_DEFAULT_LOGIN_PASSWORD=
ENV VITE_DEFAULT_LOGIN_EMAIL=${VITE_DEFAULT_LOGIN_EMAIL}
ENV VITE_DEFAULT_LOGIN_PASSWORD=${VITE_DEFAULT_LOGIN_PASSWORD}
ENV VITE_REPORTS_ENABLED=false
ENV VITE_CHAT_TRANSPORT=sse
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY backend/requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt \
    && useradd --create-home --uid 10001 nutrition
COPY --chown=10001:10001 backend/app ./app
COPY --chown=10001:10001 deploy/hosted_acceptance.py ./hosted_acceptance.py
COPY --chown=10001:10001 deploy/hosted_start.py ./hosted_start.py
COPY --from=frontend /build/dist ./static
ENV APP_STATIC_DIR=/app/static APP_MEDIA_DIR=/tmp/nutrition-media APP_NGINX_ACCEL=false
USER nutrition
EXPOSE 10000
CMD ["python", "hosted_start.py"]
