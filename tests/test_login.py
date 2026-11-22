"""Tests for the Mina sidor BankID login started from the panel (login.py)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import CookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from vafabmiljo import login
from vafabmiljo.api import VafabMiljoError
from vafabmiljo.login import KEY, async_cancel_login, ws_cancel, ws_start, ws_status
from vafabmiljo.minasidor import MinaSidorCredentials, MinaSidorLoginError

CREDS = MinaSidorCredentials(
    refresh_cookie="refresh1", refresh_expires=1800000000.0, access_token="access1", customer_id="1"
)


class FakeLogin:
    """Stands in for minasidor.MinaSidorLogin; start/poll are AsyncMocks the tests steer."""

    def __init__(self, http) -> None:
        self.http = http
        self.qr = "bankid.a.0.b"
        self.autostart_token = "tok"
        self.credentials = None
        self.start = AsyncMock()
        self.poll = AsyncMock(side_effect=self._done)
        FakeLogin.instances.append(self)
        if FakeLogin.configure is not None:
            FakeLogin.configure(self)

    async def _done(self) -> bool:
        self.credentials = CREDS
        return True

    instances: list = []
    configure = None


@pytest.fixture
def setup(monkeypatch):
    FakeLogin.instances = []
    FakeLogin.configure = None
    monkeypatch.setattr(login, "BANKID_POLL_INTERVAL", 0)
    monkeypatch.setattr(login, "MinaSidorLogin", FakeLogin)
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
    return SimpleNamespace(hass=hass, entry=entry, updates=updates, aborted=aborted, conn=Mock())


def _result(s):
    return s.conn.send_result.call_args.args[1]


async def test_login_saves_the_mina_sidor_login_and_reloads(setup):
    s = setup

    def configure(fake):
        async def waiting_then_done():
            if fake.poll.await_count == 1:
                return False
            return await fake._done()

        fake.poll.side_effect = waiting_then_done

    FakeLogin.configure = configure
    await ws_start(s.hass, s.conn, {"id": 1, "entry_id": s.entry.entry_id})
    first = _result(s)
    assert first["status"] == "waiting" and first["qr"].startswith("data:image/svg+xml")
    # universal link for phones/tablets, the bankid:/// scheme for BankID on a computer
    assert first["autostart"] == "https://app.bankid.com/?autostarttoken=tok&redirect=null"
    assert first["autostart_desktop"] == "bankid:///?autostarttoken=tok&redirect=null"
    # its own cookie jar: Criipto keeps the order in cookies
    (kwargs,) = s.hass.data["created_sessions"]
    assert isinstance(kwargs["cookie_jar"], CookieJar)

    await s.hass.data[KEY][s.entry.entry_id].task
    ws_status(s.hass, s.conn, {"id": 2, "entry_id": s.entry.entry_id})
    done = _result(s)
    assert done["status"] == "done"
    assert done["qr"] is None and done["autostart"] is None and done["autostart_desktop"] is None
    assert s.updates == [
        {
            "device_uuid": "d",
            "device_bearer": "b",
            "minasidor_refresh": "refresh1",
            "minasidor_refresh_expires": 1800000000.0,
            "minasidor_access": "access1",
        }
    ]
    # the update listener does the reload; the pending reauth flow is closed
    assert s.aborted == ["f1"]


async def test_without_qr_or_token_nothing_is_shown(setup):
    s = setup

    def configure(fake):
        fake.qr, fake.autostart_token = "", None
        fake.poll.side_effect = lambda: asyncio.sleep(10)

    FakeLogin.configure = configure
    await ws_start(s.hass, s.conn, {"id": 1, "entry_id": s.entry.entry_id})
    assert _result(s) == {"status": "waiting", "hint": None, "qr": None, "autostart": None, "autostart_desktop": None}
    async_cancel_login(s.hass, s.entry.entry_id)


async def test_bankid_failure_and_api_error_and_timeout(setup, monkeypatch):
    s = setup
    for error, hint in [(MinaSidorLoginError("userCancel"), "userCancel"), (VafabMiljoError("boom"), "boom")]:
        FakeLogin.configure = lambda fake, error=error: setattr(fake.poll, "side_effect", error)
        await ws_start(s.hass, s.conn, {"id": 1, "entry_id": s.entry.entry_id})
        await s.hass.data[KEY][s.entry.entry_id].task
        ws_status(s.hass, s.conn, {"id": 2, "entry_id": s.entry.entry_id})
        assert (_result(s)["status"], _result(s)["hint"]) == ("failed", hint)
        assert _result(s)["qr"] is None

    FakeLogin.configure = None
    monkeypatch.setattr(login, "BANKID_POLL_TIMEOUT", -1)
    await ws_start(s.hass, s.conn, {"id": 3, "entry_id": s.entry.entry_id})
    await s.hass.data[KEY][s.entry.entry_id].task
    ws_status(s.hass, s.conn, {"id": 4, "entry_id": s.entry.entry_id})
    assert _result(s)["hint"] == "timeout"
    assert s.updates == []


async def test_restart_cancels_the_previous_login_and_cancel_stops_it(setup):
    s = setup
    FakeLogin.configure = lambda fake: setattr(fake.poll, "side_effect", lambda: asyncio.sleep(10))
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
    FakeLogin.configure = lambda fake: setattr(fake.start, "side_effect", VafabMiljoError("down"))
    await ws_start(s.hass, s.conn, {"id": 2, "entry_id": s.entry.entry_id})
    assert [c.args[1] for c in s.conn.send_error.call_args_list] == ["not_found", "cannot_connect"]
    assert s.entry.entry_id not in s.hass.data.get(KEY, {})


async def test_unloading_the_entry_stops_its_login(setup):
    s = setup
    FakeLogin.configure = lambda fake: setattr(fake.poll, "side_effect", lambda: asyncio.sleep(10))
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
    first_started = asyncio.Event()

    async def pending():
        await asyncio.sleep(10)

    async def slow_start():
        first_started.set()
        await asyncio.sleep(0.01)

    def configure(fake):
        fake.poll.side_effect = pending
        fake.start.side_effect = slow_start

    FakeLogin.configure = configure
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
