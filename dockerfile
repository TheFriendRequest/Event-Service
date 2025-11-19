# Use official Python slim image
FROM python:3.12-slim

# Set workdir
WORKDIR /app

# Install system dependencies needed for pydantic-core
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    rustc \
    cargo \
    libffi-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .

# Upgrade pip and install dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . /app

# Expose port 8080
EXPOSE 8080

# Run FastAPI using Uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--reload"]
