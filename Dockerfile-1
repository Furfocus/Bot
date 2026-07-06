# Use Python 3.10
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install FFmpeg
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY music_bot.py .

# Run the bot
CMD ["python", "music_bot.py"]
