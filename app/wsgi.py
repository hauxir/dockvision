from app import app as webapp, garbage_collector


def app(*args, **kwargs):
    garbage_collector()
    return webapp(*args, **kwargs)
