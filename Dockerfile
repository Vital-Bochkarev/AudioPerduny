FROM python:3.9-slim

WORKDIR /app
COPY . .

RUN pip install python-telegram-bot aiohttp
RUN mkdir -p audio_messages

CMD ["python", "main.py"]