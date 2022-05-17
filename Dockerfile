FROM python:3.9-slim

RUN apt-get update && \
    apt-get install -y \
    curl \
    nginx

COPY requirements.txt .
COPY nginx.conf /etc/nginx/conf.d/default.conf

RUN pip install -r requirements.txt

EXPOSE 5000

COPY app /app

WORKDIR /app

CMD bash entrypoint.sh
