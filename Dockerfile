FROM python:3.9-slim

RUN apt-get update && \
    apt-get install -y \
    curl \
    nginx

COPY requirements.txt .

RUN pip install -r requirements.txt
RUN sed -i "s/80/5001/" /etc/nginx/sites-available/default

EXPOSE 5000

COPY app /app

WORKDIR /app

COPY nginx.conf /etc/nginx/conf.d/default.conf

CMD bash entrypoint.sh
