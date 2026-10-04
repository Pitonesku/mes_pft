FROM python:3.11-slim

WORKDIR /app

# Dependencies first for better layer caching (build context is backend/).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend code. The app package ends up at /app/app/.
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
