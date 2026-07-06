# Use Python 3.11
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY music_bot.py .

# Run the bot
CMD ["python", "music_bot.py"]
