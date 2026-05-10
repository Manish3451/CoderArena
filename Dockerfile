# Use Python 3.11 slim
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY arena/ ./arena/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=production

EXPOSE 8000

CMD ["uvicorn", "arena.main:app", "--host", "0.0.0.0", "--port", "8000"]