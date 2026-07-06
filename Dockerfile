# Use Python 3.10
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install FFmpeg and required audio libraries
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libffi-dev \
    libssl-dev \
    libopus0 \
    libopus-dev \
    libsodium23 \
    libsodium-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies with no cache
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY music_bot.py .

# Run the bot
CMD ["python", "music_bot.py"]
