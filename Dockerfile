FROM python:3.9-slim

WORKDIR /app
COPY . .

RUN pip install python-telegram-bot

# Run both services
CMD bash -c "python health_server.py & python main.py"