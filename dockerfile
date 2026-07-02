FROM python:3.14

WORKDIR /app
COPY ./bot /app

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python3", "./main.py"]
