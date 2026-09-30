"""Oversized photo uploads must be answered with a clear reason, not silence."""

from __future__ import annotations

import io

from images import format_bytes, upload_limit_message

LIMIT = 1024 * 1024  # TestConfig.MAX_CONTENT_LENGTH


def _upload(client, path, size, **fields):
    data = {"description": "Leaves curling", **fields}
    data["image"] = (io.BytesIO(b"\xff\xd8" + b"\0" * size), "big.jpg", "image/jpeg")
    return client.post(path, data=data, content_type="multipart/form-data")


def test_format_bytes_and_limit_message():
    assert format_bytes(12 * 1024 * 1024) == "12 MB"
    assert format_bytes(1024 * 1024 + 512 * 1024) == "1.5 MB"
    assert format_bytes(850 * 1024) == "850 KB"
    assert format_bytes(12) == "12 bytes"
    assert "1 MB limit" in upload_limit_message(LIMIT)


def test_oversized_upload_gets_an_explanatory_json_413(client, fake_ai):
    response = _upload(client, "/plant-health-records/assessments", LIMIT + 1)
    assert response.status_code == 413
    body = response.get_json()
    assert "1 MB limit" in body["error"] and body["limit_bytes"] == LIMIT
    assert fake_ai.calls == []  # rejected before any model call


def test_oversized_stream_upload_gets_the_reason_as_an_sse_event(client):
    response = _upload(client, "/plant-health-records/assessments/stream", LIMIT + 1)
    assert response.status_code == 413
    assert response.mimetype == "text/event-stream"
    text = response.get_data(as_text=True)
    assert text.startswith("data: ") and '"type": "error"' in text and "1 MB limit" in text


def test_upload_within_the_limit_is_assessed(client, fake_ai):
    response = _upload(client, "/plant-health-records/assessments", 64 * 1024)
    assert response.status_code == 201, response.get_data(as_text=True)
    assert response.get_json()["has_image"] is True
    assert fake_ai.calls[-1]["image"] is True


def test_form_tells_the_user_the_limit_up_front(client):
    html = client.get("/plant-health-records/").get_data(as_text=True)
    assert f'data-max-upload-bytes="{LIMIT}"' in html
    assert "maxUploadBytes: 1048576" in html and "maxUploadLabel: '1 MB'" in html
    assert "Up to 1 MB" in html and "shrunk in your browser" in html
