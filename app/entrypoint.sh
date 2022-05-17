#!/bin/bash
nginx
gunicorn --bind unix:server.sock wsgi:app --access-logfile -
