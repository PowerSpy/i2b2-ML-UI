import requests

from app.core.config import settings


class Etl_API_Error(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"ETL API {status}: {body[:200]}")


def etl_request(method: str, path: str, params=None, json=None, timeout=30.0):
    req = requests.request(
        method,
        settings.etl_url + path,
        headers = settings.etl_headers,
        params = params,
        json = json,
        timeout = timeout,
    )

    if not req.ok:
        raise Etl_API_Error(req.status_code, req.text)
    try:
        return req.json()
    except ValueError:
        return req.text


def get(path, **kw):
    return etl_request("GET", path, **kw)
def post(path, **kw):
    return etl_request("POST", path, **kw)
def put(path, **kw):
    return etl_request("PUT", path, **kw)
def delete(path, **kw):
    return etl_request("DELETE", path, **kw)
