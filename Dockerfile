FROM python:3.9-slim

WORKDIR /app
COPY . .

RUN pip install python-telegram-bot

CMD ["python", "main.py"]