import base64
import json

from pulse import aws_lambda


def url_event(method: str, path: str, query: str = "", body: bytes | None = None) -> dict:
    """The shape of a Lambda function URL request (payload format 2.0)."""
    event = {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": query,
        "headers": {"content-type": "application/json"},
        "requestContext": {"http": {"method": method, "path": path}},
        "isBase64Encoded": False,
    }
    if body is not None:
        event["body"] = base64.b64encode(body).decode()
        event["isBase64Encoded"] = True
    return event


def body_of(response: dict):
    return json.loads(base64.b64decode(response["body"]))


def test_function_url_requests_reach_the_app(sessions):
    response = aws_lambda.http_handler(url_event("GET", "/up"), None)
    assert response["statusCode"] == 200
    assert body_of(response) == {"ok": True}

    response = aws_lambda.http_handler(url_event("GET", "/api/incidents", "limit=5"), None)
    assert response["statusCode"] == 200
    assert body_of(response) == []


def test_request_bodies_and_validation_errors_pass_through(sessions):
    payload = json.dumps({"name": "Local", "url": "ftp://example.com"}).encode()
    response = aws_lambda.http_handler(url_event("POST", "/api/monitors", body=payload), None)
    assert response["statusCode"] == 422


def test_the_scheduled_round_runs_on_the_same_loop_each_time(sessions, monkeypatch):
    monkeypatch.setattr(aws_lambda, "SessionFactory", sessions)
    assert aws_lambda.check_handler({}, None) == {"checked": 0}
    assert aws_lambda.check_handler({}, None) == {"checked": 0}
