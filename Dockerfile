FROM python:3.9-slim

WORKDIR /app

COPY . .

RUN pip install python-telegram-bot==20.7 aiohttp
RUN mkdir -p audio_messages
RUN pip install -r requirements.txt

CMD ["python", "main.py"]