import functools
import cachetools.func

from flask import Flask, jsonify, request, send_from_directory, Response
import docker

app = Flask(__name__)
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = True

docker_client = docker.from_env()

LABEL = "dockvision"


def get_containers():
    return [
        c for c in docker_client.containers.list() if LABEL in list(c.labels.keys())
    ]


def get_container(container_id):
    containers = get_containers()
    return next(
        c for c in containers if c.__dict__["attrs"]["Id"].startswith(container_id)
    )


@cachetools.func.ttl_cache(ttl=5 * 60)
def get_docker_ip_and_port(container_id):
    container = get_container(container_id)
    port = next(
        k for k in container.labels.keys() if k.startswith("dockvision-port")
    ).split("dockvision-port-")[1]
    ip = container.attrs["NetworkSettings"]["IPAddress"]
    return ip, port


def run_container(image, port):
    return docker_client.containers.run(
        image,
        detach=True,
        labels=["dockvision", f"dockvision-port-{port}"],
        environment=dict(
            NEKO_ICESERVERS='[{"urls": ["turn:turn.cloud.kosmi.dev:8000"], "username": "user", "credential": "root"}]',
            NEKO_IMPLICIT_CONTROL="true",
            NEKO_H264="true",
            NEKO_VIDEO_BITRATE=500,
            NEKO_MAX_FPS=30,
            NEKO_AUDIO_BITRATE=128,
        ),
    )


def stop_container(container_id):
    container = get_container(container_id)
    container.stop()
    container.remove()


def docker_proxy(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        host = request.headers.get("X-Forwarded-Host")
        container_id = host.split(".")[0]
        if container_id != "admin":
            ip_address, port = get_docker_ip_and_port(container_id)
            resp = Response()
            resp.headers["X-Accel-Redirect"] = (
                f"/nginx/{ip_address}:{port}" + request.full_path
            )
            resp.headers["Referrer-Policy"] = "no-referrer-when-downgrade"
            return resp
        return func(*args, **kwargs)

    return wrapper


@app.route("/start", methods=["POST"])
@docker_proxy
def start():
    image = dict(request.form).get("image")
    port = dict(request.form).get("port")
    container = run_container(image, port)
    return jsonify(id=container.__dict__["attrs"]["Id"][:5])


@app.route("/stop", methods=["POST"])
@docker_proxy
def stop():
    container_id = dict(request.form).get("container_id")
    stop_container(container_id)
    return jsonify()


@app.route("/containers")
@docker_proxy
def containers():
    containers = get_containers()
    serialized_containers = [
        dict(
            id=c.__dict__["attrs"]["Id"],
            image=c.__dict__["attrs"]["Config"]["Image"],
            status=c.__dict__["attrs"]["State"]["Status"],
            port=get_docker_ip_and_port(c.__dict__["attrs"]["Id"])[1],
        )
        for c in containers
    ]
    return jsonify(containers=serialized_containers)


@app.route("/", defaults={"path": ""})
@app.route("/<string:path>")
@app.route("/<path:path>")
@docker_proxy
def root(path):
    return Response("Dockvision")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
