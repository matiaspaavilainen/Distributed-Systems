FROM python:3.12.8-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY startup.sh /app/startup.sh
RUN chmod +x /app/startup.sh

# Copy the source code into the container.
COPY . .

CMD ["python", "main.py"]