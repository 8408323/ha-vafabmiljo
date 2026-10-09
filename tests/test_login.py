"""Tests for the BankID login started from the panel (login.py)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from vafabmiljo import login
from vafabmiljo.api import VafabMiljoError
from vafabmiljo.login import KEY, async_cancel_login, ws_cancel, ws_start, ws_status

OK = {"status": "authenticated successfully", "qr": "", "hint": ""}
FAILED = {"status": {"message": {"status": "failed", "hintCode": "startFailed"}}}


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(login, "BANKID_POLL_INTERVAL", 0)
    client = Mock(session_cookie="new-cookie")
    client.start_bankid_auth = AsyncMock(return_value={"qr": "<svg>1</svg>", "token": "tok"})
    client.poll_bankid_status = AsyncMock(return_value=OK)
    monkeypatch.setattr(login, "VafabMiljoClient", lambda *a: client)
    hass = HomeAssistant()
    hass.data["test_session"] = object()
    hass.async_create_background_task = lambda coro, name: asyncio.ensure_future(coro)
    entry = ConfigEntry(data={"device_uuid": "d", "device_bearer": "b", "session_cookie": "old"})
    updates, aborted = [], []
    reauth = [{"flow_id": "f1", "context": {"source": "reauth", "entry_id": entry.entry_id}}]
    flow = SimpleNamespace(
        async_progress_by_handler=lambda domain, match_context: [
            f for f in reauth if all(f["context"].get(k) == v for k, v in match_context.items())
        ],
        async_abort=aborted.append,
    )
    hass.config_entries = SimpleNamespace(
        async_get_entry=lambda eid: entry if eid == entry.entry_id else None,
        async_update_entry=lambda e, data: updates.append(data),
        flow=flow,
    )
    return SimpleNamespace(hass=hass, entry=entry, client=client, updates=updates, aborted=aborted, conn=Mock())


def _result(s):
    return s.conn.send_result.call_args.args[1]


async def test_login_saves_the_cookie_and_reloads(setup):
    s = setup
    s.client.poll_bankid_status.side_effect = [{"qr": "<svg>2</svg>"}, OK]
    await ws_start(s.hass, s.conn, {"id": 1, "entry_id": s.entry.entry_id})
    first = _result(s)
    assert first["status"] == "waiting" and first["qr"].startswith("data:image/svg+xml;base64,")
    assert first["autostart"] == "bankid:///?autostarttoken=tok&redirect=null"

    await s.hass.data[KEY][s.entry.entry_id].task
    ws_status(s.hass, s.conn, {"id": 2, "entry_id": s.entry.entry_id})
    assert _result(s)["status"] == "done" and _result(s)["qr"] is None
    assert s.updates == [{**s.entry.data, "session_cookie": "new-cookie"}]
    # the update listener does the reload; the pending reauth flow is closed
    assert s.aborted == ["f1"]


async def test_bankid_failure_and_api_error_and_timeout(setup, monkeypatch):
    s = setup
    for side_effect, hint in [(FAILED, "startFailed"), (VafabMiljoError("boom"), "boom")]:
        s.client.poll_bankid_status.side_effect = [side_effect]
        await ws_start(s.hass, s.conn, {"id": 1, "entry_id": s.entry.entry_id})
        await s.hass.data[KEY][s.entry.entry_id].task
        ws_status(s.hass, s.conn, {"id": 2, "entry_id": s.entry.entry_id})
        assert (_result(s)["status"], _result(s)["hint"]) == ("failed", hint)

    monkeypatch.setattr(login, "BANKID_POLL_TIMEOUT", -1)
    await ws_start(s.hass, s.conn, {"id": 3, "entry_id": s.entry.entry_id})
    await s.hass.data[KEY][s.entry.entry_id].task
    ws_status(s.hass, s.conn, {"id": 4, "entry_id": s.entry.entry_id})
    assert _result(s)["hint"] == "timeout"
    assert s.updates == []


async def test_restart_cancels_the_previous_login_and_cancel_stops_it(setup):
    s = setup
    s.client.poll_bankid_status.side_effect = lambda: asyncio.sleep(10)
    await ws_start(s.hass, s.conn, {"id": 1, "entry_id": s.entry.entry_id})
    first = s.hass.data[KEY][s.entry.entry_id]
    await ws_start(s.hass, s.conn, {"id": 2, "entry_id": s.entry.entry_id})
    await asyncio.sleep(0)
    assert first.task.cancelled() or first.task.cancelling()

    second = s.hass.data[KEY][s.entry.entry_id]
    ws_cancel(s.hass, s.conn, {"id": 3, "entry_id": s.entry.entry_id})
    await asyncio.sleep(0)
    assert second.task.cancelled() or second.task.cancelling()
    ws_cancel(s.hass, s.conn, {"id": 4, "entry_id": s.entry.entry_id})  # nothing left: still fine
    ws_status(s.hass, s.conn, {"id": 5, "entry_id": s.entry.entry_id})
    assert _result(s) == {"status": "none"}


async def test_start_errors(setup):
    s = setup
    await ws_start(s.hass, s.conn, {"id": 1, "entry_id": "nope"})
    s.client.start_bankid_auth.side_effect = VafabMiljoError("down")
    await ws_start(s.hass, s.conn, {"id": 2, "entry_id": s.entry.entry_id})
    assert [c.args[1] for c in s.conn.send_error.call_args_list] == ["not_found", "cannot_connect"]
    assert s.entry.entry_id not in s.hass.data.get(KEY, {})


async def test_unloading_the_entry_stops_its_login(setup):
    s = setup
    s.client.poll_bankid_status.side_effect = lambda: asyncio.sleep(10)
    await ws_start(s.hass, s.conn, {"id": 1, "entry_id": s.entry.entry_id})
    running = s.hass.data[KEY][s.entry.entry_id]
    async_cancel_login(s.hass, s.entry.entry_id)
    await asyncio.sleep(0)
    assert running.task.cancelled() or running.task.cancelling()
    assert s.entry.entry_id not in s.hass.data[KEY]


async def test_a_finished_login_survives_the_reload_it_triggers(setup):
    s = setup
    await ws_start(s.hass, s.conn, {"id": 1, "entry_id": s.entry.entry_id})
    await s.hass.data[KEY][s.entry.entry_id].task
    async_cancel_login(s.hass, s.entry.entry_id)  # the update listener's reload unloads the entry
    ws_status(s.hass, s.conn, {"id": 2, "entry_id": s.entry.entry_id})
    assert _result(s)["status"] == "done"


async def test_concurrent_starts_leave_only_one_login_running(setup):
    s = setup

    async def pending():
        await asyncio.sleep(10)

    s.client.poll_bankid_status.side_effect = pending
    first_started = asyncio.Event()

    async def slow_start():
        first_started.set()
        await asyncio.sleep(0.01)
        return {"qr": "<svg/>", "token": "t"}

    s.client.start_bankid_auth.side_effect = slow_start
    msg = {"id": 1, "entry_id": s.entry.entry_id}
    a = asyncio.ensure_future(ws_start(s.hass, s.conn, msg))
    await first_started.wait()
    b = asyncio.ensure_future(ws_start(s.hass, s.conn, msg))  # a double click
    await asyncio.gather(a, b)
    await asyncio.sleep(0)

    running = s.hass.data[KEY][s.entry.entry_id]
    tasks = [t for t in asyncio.all_tasks() if t.get_coro().__qualname__ == "PanelLogin._poll" and not t.done()]
    assert tasks == [running.task]  # the first one was cancelled, none orphaned
    async_cancel_login(s.hass, s.entry.entry_id)
