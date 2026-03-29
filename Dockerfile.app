FROM python:3.12-slim

# System deps for Playwright, curl-cffi, spaCy, and asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    wget \
    git \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libatspi2.0-0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONPATH=/app

# Install Poetry + pipx
RUN pip install --no-cache-dir poetry==1.8.2 pipx \
    && pipx ensurepath

# Copy dependency files first (Docker cache layer)
COPY pyproject.toml poetry.lock* requirements.txt ./

# Install Python dependencies
# Poetry handles main deps; pip adds runtime extras not in pyproject.toml
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root \
    && pip install --no-cache-dir python-dotenv

# Install CLI tools in isolated envs (networkx version conflicts with main deps)
RUN pipx install sherlock-project \
    && pipx install maigret \
    && ln -sf /root/.local/bin/sherlock /usr/local/bin/sherlock \
    && ln -sf /root/.local/bin/maigret /usr/local/bin/maigret

# Install spaCy model and Playwright browsers
RUN python -m spacy download en_core_web_lg \
    && playwright install chromium --with-deps

# Copy application source
COPY . .

EXPOSE 8000
