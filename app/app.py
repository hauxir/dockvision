import functools
import os
import requests
import threading
import time
import urllib3

import cachetools.func
import docker
from flask import Flask, jsonify, request, send_from_directory, Response, abort

app = Flask(__name__)
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = True

docker_client = docker.from_env()

LABEL = "dockvision"

HTTP_METHODS = [
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "DELETE",
    "CONNECT",
    "OPTIONS",
    "TRACE",
    "PATCH",
]

CONTAINER_IDLE_TIMEOUT = 15 * 60


timestamps = dict()


def get_containers():
    return [
        c for c in docker_client.containers.list() if LABEL in list(c.labels.keys())
    ]


def get_container(container_id):
    containers = get_containers()
    try:
        return next(
            c for c in containers if c.__dict__["attrs"]["Id"].startswith(container_id)
        )
    except StopIteration:
        return None


def threaded(fn):
    def wrapper(*args, **kwargs):
        thread = threading.Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        return thread

    return wrapper


@cachetools.func.ttl_cache(ttl=5 * 60)
def get_docker_ip_and_port(container_id):
    container = get_container(container_id)
    if container:
        port = next(
            k for k in container.labels.keys() if k.startswith(f"{LABEL}-port")
        ).split("dockvision-port-")[1]
        ip = container.attrs["NetworkSettings"]["IPAddress"]
        return ip, port
    return None, None


def run_container(image, port, environment=dict()):
    container = docker_client.containers.run(
        image,
        detach=True,
        labels=[LABEL, f"{LABEL}-port-{port}"],
        environment=environment,
    )
    container_id = container.__dict__["attrs"]["Id"][:5]
    timestamps[container_id] = time.time()
    return container_id


def stop_container(container_id):
    container = get_container(container_id)
    container_id = container.__dict__["attrs"]["Id"][:5]
    if container:
        container.stop()
        container.remove()
    timestamps.pop(container_id, None)


def docker_proxy(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        host = request.headers.get("X-Forwarded-Host") or ""
        container_id = host.split(".")[0][:5]
        if container_id != "admin":
            ip_address, port = get_docker_ip_and_port(container_id)
            if ip_address is None or port is None:
                abort(404)
            timestamps[container_id] = time.time()
            resp = Response()
            resp.headers["X-Accel-Redirect"] = (
                f"/nginx/{ip_address}:{port}" + request.full_path
            )
            resp.headers["Referrer-Policy"] = "no-referrer-when-downgrade"
            return resp
        return func(*args, **kwargs)

    return wrapper


def auth(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        token = request.headers.get("X-Token")
        if os.environ.get("TOKEN") and os.environ.get("TOKEN") != token:
            abort(401)
        return func(*args, **kwargs)

    return wrapper


@app.route("/start", methods=["POST"])
@auth
@docker_proxy
def start():
    form = request.get_json(force=True)
    image = form.get("image")
    port = form.get("port")
    environment = form.get("environment", dict())
    container_id = run_container(image, port, environment=environment)
    host = request.headers.get("X-Forwarded-Host")
    proto = request.headers.get("X-Forwarded-Proto")
    url = f"{proto}://{container_id}." + ".".join(host.split(".")[1:])
    return jsonify(id=container_id, url=url)


@app.route("/stop", methods=["POST"])
@auth
@docker_proxy
def stop():
    form = request.get_json(force=True)
    container_id = form.get("container_id")
    stop_container(container_id)
    return jsonify()


@app.route("/containers")
@auth
@docker_proxy
def containers():
    containers = get_containers()
    serialized_containers = [
        dict(
            id=c.__dict__["attrs"]["Id"][:5],
            image=c.__dict__["attrs"]["Config"]["Image"],
            status=c.__dict__["attrs"]["State"]["Status"],
            port=get_docker_ip_and_port(c.__dict__["attrs"]["Id"])[1],
            timestamp=timestamps.get(c.__dict__["attrs"]["Id"][:5]),
        )
        for c in containers
    ]
    return jsonify(containers=serialized_containers)


@app.route("/", defaults={"path": ""}, methods=HTTP_METHODS)
@app.route("/<string:path>", methods=HTTP_METHODS)
@app.route("/<path:path>", methods=HTTP_METHODS)
@docker_proxy
def root(path):
    abort(404)


@threaded
def garbage_collector():
    while True:
        try:
            containers = get_containers()
            container_ids = [c.__dict__["attrs"]["Id"][:5] for c in containers]

            timestamp_container_ids = list(timestamps.keys())
            containers_without_timestamp = [
                cid for cid in container_ids if cid not in timestamp_container_ids
            ]

            for cid in containers_without_timestamp:
                stop_container(cid)

            now = time.time()
            for cid in timestamp_container_ids:
                timestamp = timestamps[cid]
                if (now - timestamp) >= CONTAINER_IDLE_TIMEOUT:
                    stop_container(cid)
        except Exception as e:
            print(e)
        time.sleep(30)
