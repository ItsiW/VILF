from os import environ
from subprocess import run

from fastapi import FastAPI

app = FastAPI()


@app.post("/deploy")
def deploy():
    run([environ["VILF_DEPLOY"]])
