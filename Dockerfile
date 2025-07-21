FROM python:3.9-slim

WORKDIR /app

COPY . .

RUN pip install python-telegram-bot==20.7 aiohttp firebase-admin google-cloud-firestore
RUN mkdir -p audio_messages

CMD ["python", "main.py"]