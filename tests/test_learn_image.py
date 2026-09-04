"""Learn accepts an attached image and answers in TEXT.

The point of the move: the same photo on the Teach front door starts a four-minute video build.
In Learn it costs one vision call and comes back as an answer, with a video only if the existing
"worth a video" offer fires.
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from web import seed

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI

    from web import jobs as jobs_mod
    from web import learn

    calls = {"vision": [], "chat": []}

    def fake_describe(data_url, question="", *, client=None):
        seed.validate(data_url)                 # keep the real guard in the path
        calls["vision"].append((data_url, question))
        return "a right triangle with legs 3 and 4, hypotenuse unlabelled"

    class FakeLLM:
        def chat(self, messages, **kw):
            calls["chat"].append(messages)
            return '{"answer": "The hypotenuse is 5.", "offer": false, ' \
                   '"offer_label": "", "video_prompt": ""}'

    monkeypatch.setattr("web.seed.describe", fake_describe)
    monkeypatch.setattr("core.llm.get_client", lambda **kw: FakeLLM())

    # Mount Learn on a bare app via its own register() — web/app.py does not wire it on this
    # branch (that wiring lives in the other session's work), and this is tighter isolation anyway.
    engine = SimpleNamespace(root=tmp_path)     # Learn only needs .root
    app = FastAPI()
    learn.register(app, engine, jobs_mod.JobQueue(synchronous=True))
    c = TestClient(app)
    c.calls = calls
    return c


@pytest.mark.unit
def test_an_attached_image_is_read_and_answered_as_text(client):
    r = client.post("/api/learn/threads", json={"message": "what's the hypotenuse?", "image": PNG})
    assert r.status_code == 200
    thread = r.json()

    assert len(client.calls["vision"]) == 1                    # exactly one paid vision call
    assert client.calls["vision"][0][1] == "what's the hypotenuse?"   # the question steers it

    msgs = thread["messages"]
    assert msgs[-1]["kind"] == "text"                          # a text answer, not a video job
    assert msgs[-1]["text"] == "The hypotenuse is 5."


@pytest.mark.unit
def test_the_description_reaches_the_chat_but_the_base64_never_does(client):
    client.post("/api/learn/threads", json={"message": "what's the hypotenuse?", "image": PNG})
    sent = client.calls["chat"][0][-1]["content"]
    assert "right triangle with legs 3 and 4" in sent       # the model can "see" it
    assert PNG not in sent                                   # ...without being handed the payload


@pytest.mark.unit
def test_the_thread_stores_a_flag_not_the_image(client, tmp_path):
    """A thread is a JSON file on disk. Storing base64 would add megabytes per message for
    something no later turn re-reads."""
    thread = client.post("/api/learn/threads",
                         json={"message": "what's this?", "image": PNG}).json()
    user_msg = thread["messages"][0]
    assert user_msg["text"] == "what's this?"      # the learner's own words, unpolluted
    assert user_msg["has_image"] is True           # ...plus a flag the UI can render a chip from
    assert PNG not in str(thread)

    on_disk = next(tmp_path.rglob("thread.json"), None) or next(tmp_path.rglob("*.json"))
    assert PNG not in on_disk.read_text(encoding="utf-8")


@pytest.mark.unit
def test_a_follow_up_message_can_attach_too(client):
    tid = client.post("/api/learn/threads", json={"message": "hi"}).json()["id"]
    assert client.calls["vision"] == []                        # no image, no vision call

    client.post(f"/api/learn/threads/{tid}/messages",
                json={"message": "and this one?", "image": PNG})
    assert len(client.calls["vision"]) == 1


@pytest.mark.unit
def test_an_unreadable_image_still_gets_an_answer(client, monkeypatch):
    """Best-effort: vision failing must not cost the learner their turn."""
    def boom(data_url, question="", *, client=None):
        raise seed.SeedError("image too large (max ~5 MB)")

    monkeypatch.setattr("web.seed.describe", boom)
    r = client.post("/api/learn/threads", json={"message": "what's this?", "image": PNG})
    assert r.status_code == 200
    assert r.json()["messages"][-1]["text"] == "The hypotenuse is 5."
    assert "could not be read" in client.calls["chat"][0][-1]["content"]


@pytest.mark.unit
def test_describe_rejects_a_non_image_payload():
    with pytest.raises(seed.SeedError):
        seed.describe("data:text/html;base64,PHNjcmlwdD4=")
    with pytest.raises(seed.SeedError):
        seed.describe("https://example.com/cat.png")


@pytest.mark.unit
def test_describe_asks_the_vision_model_not_to_answer():
    """It must DESCRIBE. If it answers instead, the chat model gets a conclusion it can't check
    and the thread's reasoning stops being visible to the learner."""
    seen = {}

    class FakeVision:
        def chat(self, messages, **kw):
            seen["content"] = messages[0]["content"]
            seen["max_tokens"] = kw.get("max_tokens")
            return "a right triangle"

    out = seed.describe(PNG, "what's the hypotenuse?", client=FakeVision())
    assert out == "a right triangle"
    text = seen["content"][0]["text"]
    assert "Do not answer the question yourself" in text
    assert "what's the hypotenuse?" in text
    assert seen["content"][1]["image_url"]["url"] == PNG
    assert seen["max_tokens"] == seed.DESCRIBE_MAX_TOKENS      # bounded output cost
