"""API Mini App: initData, изоляция данных, избранное, озвучка, админка."""

import time

from app.api.auth import InitDataError, verify_init_data
from tests.conftest import auth, sign_init_data

import pytest


def test_init_data_signature():
    good = sign_init_data(42)
    assert verify_init_data(good, "123456:TEST-TOKEN", 3600).id == 42
    with pytest.raises(InitDataError):
        verify_init_data(good, "999:OTHER-TOKEN", 3600)  # чужой токен
    tampered = good.replace("%22id%22%3A42", "%22id%22%3A43")
    assert tampered != good
    with pytest.raises(InitDataError):
        verify_init_data(tampered, "123456:TEST-TOKEN", 3600)  # подменён user
    old = sign_init_data(42, auth_date=int(time.time()) - 7200)
    with pytest.raises(InitDataError):
        verify_init_data(old, "123456:TEST-TOKEN", 3600)  # просрочено


async def test_requires_auth(api):
    assert (await api.get("/api/me")).status_code == 401
    r = await api.get("/api/me", headers={"Authorization": "tma user=%7B%22id%22%3A1%7D&hash=00"})
    assert r.status_code == 401
    # Режим разработки (X-Dev-User) в prod не работает
    assert (await api.get("/api/me", headers={"X-Dev-User": "1"})).status_code == 401


async def test_search_and_history(api):
    r = await api.post("/api/search", json={"q": "baliq"}, headers=auth(501))
    assert r.status_code == 200 and r.json()["cards"][0]["headword"] == "鱼"
    h = (await api.get("/api/history", headers=auth(501))).json()
    assert h[0]["query"] == "baliq"
    assert (await api.get("/api/history", headers=auth(502))).json() == []  # другой пользователь
    await api.delete("/api/history", headers=auth(501))
    assert (await api.get("/api/history", headers=auth(501))).json() == []


async def test_favorites_add_remove_isolated(api):
    body = {"headword": "鱼", "pinyin": "yú", "gloss": "baliq", "entry_id": None}
    fav = (await api.post("/api/favorites", json=body, headers=auth(601))).json()
    assert (await api.get("/api/favorites", headers=auth(601))).json()[0]["headword"] == "鱼"
    # Другой пользователь не видит и не может удалить
    assert (await api.get("/api/favorites", headers=auth(602))).json() == []
    assert (await api.delete(f"/api/favorites/{fav['id']}", headers=auth(602))).status_code == 404
    # Отметка в выдаче поиска
    r = (await api.post("/api/search", json={"q": "鱼"}, headers=auth(601))).json()
    assert r["cards"][0]["readings"][0]["favorite_id"] == fav["id"]
    # Повторение
    nxt = (await api.get("/api/review/next", headers=auth(601))).json()
    assert nxt["headword"] == "鱼"
    assert (await api.post(f"/api/review/{fav['id']}", json={"knew": True},
                           headers=auth(601))).status_code == 200
    assert (await api.delete(f"/api/favorites/{fav['id']}", headers=auth(601))).status_code == 200
    assert (await api.get("/api/favorites", headers=auth(601))).json() == []


async def test_tts(api, google):
    r = await api.get("/api/tts", params={"text": "鱼"}, headers=auth(701))
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"AUDIO:\xe9\xb1\xbc:1.0"
    r = await api.get("/api/tts", params={"text": "我喜欢吃鱼。", "slow": "true"}, headers=auth(701))
    assert r.content.endswith(b":0.7")
    n = len(google.calls)
    await api.get("/api/tts", params={"text": "鱼"}, headers=auth(701))
    assert len(google.calls) == n  # повтор — из кэша
    assert (await api.get("/api/tts", params={"text": "hello"}, headers=auth(701))).status_code == 400


async def test_tts_not_configured(api, make_services):
    from app.api.main import app
    app.state.services = make_services(google_api_key="")
    me = (await api.get("/api/me", headers=auth(702))).json()
    assert me["services"]["tts"] is False and me["services"]["translate"] is False
    r = await api.get("/api/tts", params={"text": "鱼"}, headers=auth(702))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "tts_unavailable"


async def test_tts_service_down(api, google):
    google.fail = True
    r = await api.get("/api/tts", params={"text": "水"}, headers=auth(703))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "tts_failed"


async def test_admin_access(api):
    assert (await api.get("/api/admin/stats", headers=auth(801))).status_code == 403
    r = await api.get("/api/admin/stats", headers=auth(1000))
    assert r.status_code == 200 and "services" in r.json()
    # отчёт об ошибке → админ видит → закрывает
    await api.post("/api/report", json={"query": "鱼", "message": "tekshirish"}, headers=auth(801))
    reps = (await api.get("/api/admin/reports", headers=auth(1000))).json()
    assert reps[0]["message"] == "tekshirish"
    assert (await api.post(f"/api/admin/reports/{reps[0]['id']}/resolve",
                           headers=auth(1000))).status_code == 200
    # редактирование словаря
    body = {"simplified": "猫", "traditional": "貓", "pinyin": "mao1",
            "senses": [{"uz": ["mushuk"], "ru": ["кошка"]}], "verified": True}
    assert (await api.post("/api/admin/entries", json=body, headers=auth(801))).status_code == 403
    created = (await api.post("/api/admin/entries", json=body, headers=auth(1000))).json()
    r = (await api.post("/api/search", json={"q": "mushuk"}, headers=auth(801))).json()
    assert r["cards"][0]["headword"] == "猫"
    assert r["cards"][0]["readings"][0]["senses"][0]["verified"] is True
    # отключение функции админом
    await api.put("/api/admin/flags", json={"flags": {"tts": False}}, headers=auth(1000))
    me = (await api.get("/api/me", headers=auth(801))).json()
    assert me["services"]["tts"] is False
    await api.put("/api/admin/flags", json={"flags": {"tts": True}}, headers=auth(1000))
    assert (await api.delete(f"/api/admin/entries/{created['id']}",
                             headers=auth(1000))).status_code == 200


async def test_delete_all_data(api):
    await api.post("/api/search", json={"q": "鱼"}, headers=auth(901))
    await api.post("/api/favorites", json={"headword": "鱼", "pinyin": "yú"}, headers=auth(901))
    assert (await api.delete("/api/me", headers=auth(901))).status_code == 200
    assert (await api.get("/api/history", headers=auth(901))).json() == []
    assert (await api.get("/api/favorites", headers=auth(901))).json() == []
