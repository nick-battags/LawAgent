bind = "0.0.0.0:5000"
workers = 1
worker_class = "gthread"
threads = 4
timeout = 120
graceful_timeout = 10
max_requests = 800
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
loglevel = "info"

def on_starting(server):
    server.log.info("Gunicorn master starting (pid %s)", server.pid)

def post_fork(server, worker):
    server.log.info("Worker spawned (pid %s)", worker.pid)

def worker_exit(server, worker):
    server.log.info("Worker exiting (pid %s)", worker.pid)

def on_exit(server):
    server.log.info("Gunicorn master shutting down")
