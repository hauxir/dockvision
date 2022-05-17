from flask import Flask, jsonify, request, send_from_directory, Response
import docker

app = Flask(__name__)
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True

docker_client = docker.from_env()

LABEL = "dockvision"


@app.route("/", methods=["GET"])
def root():
    resp = Response()
    resp.headers["X-Accel-Redirect"] = "/nginx/172.17.0.7"
    resp.headers["Referrer-Policy"] = "no-referrer-when-downgrade"
    return resp


def get_containers():
    return [c for c in docker_client.containers.list() if LABEL in list(c.labels.keys())]


def run_container(image):
    return docker_client.containers.run(image,detach=True, labels=["dockvision"])


@app.route("/start", methods=["POST"])
def start():
    image = request.form.get("image")
    container = run_container(image)
    return jsonify(id=container.__dict__["attrs"]["Id"])


@app.route("/containers")
def containers():
    containers = get_containers()
    serialized_containers = [dict(image=c.__dict__["attrs"]["Config"]["Image"], id=c.__dict__["attrs"]["Id"], status=c.__dict__["attrs"]["State"]["Status"])for c in containers]
    return jsonify(containers=serialized_containers)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
