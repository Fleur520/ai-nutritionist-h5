FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && \
    groupadd -g 10001 nutrition && useradd -u 10001 -g nutrition -M nutrition
COPY app /app/app
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
