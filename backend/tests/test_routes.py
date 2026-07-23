from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import File


async def seed_files(session_factory, count: int) -> list[int]:
    async with session_factory() as session:
        ids = []
        base = datetime.now(UTC)
        for i in range(count):
            f = File(
                name=f"file_{i:02d}.txt",
                content=str(i % 10) * 500,
                downloaded_at=base + timedelta(seconds=i),
            )
            session.add(f)
            await session.flush()
            ids.append(f.id)
        await session.commit()
        return ids


async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_files_empty(client):
    resp = await client.get("/api/files")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


async def test_files_pagination_and_sort(client, session_factory):
    await seed_files(session_factory, 25)

    resp = await client.get("/api/files", params={"page": 2, "per_page": 10, "sort": "asc"})
    body = resp.json()
    assert body["total"] == 25
    assert body["pages"] == 3
    assert len(body["items"]) == 10
    assert body["items"][0]["name"] == "file_10.txt"

    resp = await client.get("/api/files", params={"page": 1, "per_page": 10, "sort": "desc"})
    body = resp.json()
    assert body["items"][0]["name"] == "file_24.txt"

    # время скачивания отдаётся и по Новосибирску
    assert "downloaded_at_nsk" in body["items"][0]


async def test_files_nsk_time_value(client, session_factory):
    # naive datetime из SQLite должен трактоваться как UTC, а не как локальное время ОС
    moment = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    async with session_factory() as session:
        session.add(File(name="tz.txt", content="x", downloaded_at=moment))
        await session.commit()

    resp = await client.get("/api/files")
    item = resp.json()["items"][0]
    expected = moment.astimezone(ZoneInfo("Asia/Novosibirsk")).strftime("%d.%m.%Y %H:%M:%S")
    assert item["downloaded_at_nsk"] == expected


async def test_files_search(client, session_factory):
    await seed_files(session_factory, 25)

    resp = await client.get("/api/files", params={"search": "file_2"})
    body = resp.json()
    assert body["total"] == 5  # file_20..file_24
    assert all("file_2" in item["name"] for item in body["items"])

    resp = await client.get("/api/files", params={"search": "нет_такого"})
    assert resp.json()["total"] == 0


async def test_job_status_null(client):
    resp = await client.get("/api/job/status")
    assert resp.status_code == 200
    assert resp.json() is None


async def test_stats_by_ids(client, session_factory):
    ids = await seed_files(session_factory, 3)  # содержимое: '0'*500, '1'*500, '2'*500

    resp = await client.post("/api/stats", json={"file_ids": ids[:2]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"]["0"] == 500
    assert body["total"]["1"] == 500
    assert body["total"]["2"] == 0
    assert len(body["files"]) == 2
    assert body["files"][0]["counts"]["0"] == 500


async def test_stats_all(client, session_factory):
    await seed_files(session_factory, 10)  # цифры 0..9 по 500 каждая

    resp = await client.post("/api/stats", json={"all": True})
    assert resp.status_code == 200
    body = resp.json()
    assert all(body["total"][str(d)] == 500 for d in range(10))
    assert len(body["files"]) == 10


async def test_stats_requires_selection(client):
    resp = await client.post("/api/stats", json={})
    assert resp.status_code == 422
