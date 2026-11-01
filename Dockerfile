FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 POETRY_VIRTUALENVS_CREATE=false
WORKDIR /app
RUN pip install --no-cache-dir "poetry>=2,<3"
COPY pyproject.toml poetry.lock README.md ./
COPY src ./src
RUN poetry install --only main --no-interaction --no-ansi
# Cloud Run injects $PORT
CMD exec uvicorn cafe_companion.main:app --host 0.0.0.0 --port ${PORT:-8080}
