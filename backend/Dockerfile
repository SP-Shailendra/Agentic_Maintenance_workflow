FROM python:3.11-slim

WORKDIR /workspace
COPY backend/ ./backend/
COPY data/ ./data/
RUN python -m pip install --no-cache-dir --upgrade pip wheel \
	&& python -m pip install --no-cache-dir "setuptools==83.0.0" \
	&& python -m pip install --no-cache-dir ./backend

WORKDIR /workspace/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
