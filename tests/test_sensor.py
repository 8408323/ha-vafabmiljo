"""Tests for VafabMiljö sensor entities."""

from __future__ import annotations

from datetime import date
from unittest.mock import Mock

from homeassistant.config_entries import ConfigEntry
from vafabmiljo.coordinator import VafabMiljoData
from vafabmiljo.sensor import (
    VafabMiljoContractFeeSensor,
    VafabMiljoInvoiceSensor,
    VafabMiljoPickupSensor,
    async_setup_entry,
)


def _entry(**data) -> ConfigEntry:
    return ConfigEntry(data={"address": "Testgatan 1", "city": "Teststad", "plant_id": "p1", **data})


def _coordinator(data: VafabMiljoData) -> Mock:
    coordinator = Mock()
    coordinator.data = data
    return coordinator


async def test_setup_creates_pickup_sensors_only_when_unauthenticated():
    entry = _entry()
    entry.runtime_data = _coordinator(
        VafabMiljoData(
            pickups=[{"bins": [{"type": "Restavfall", "pickup_date": "2026-07-13"}]}],
            authenticated=False,
        )
    )
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)

    assert len(added) == 1
    assert isinstance(added[0], VafabMiljoPickupSensor)


async def test_setup_adds_invoice_and_contract_sensors_when_authenticated():
    entry = _entry()
    entry.runtime_data = _coordinator(
        VafabMiljoData(
            pickups=[{"bins": [{"type": "Restavfall", "pickup_date": "2026-07-13"}]}],
            authenticated=True,
            invoices={"data": [{"item": {"amount": 817}}]},
            sanitation={
                "contracts": [{"id": 1, "description": "Fast avgift", "fee": {"price": 1234.56, "unit": "kr/år"}}]
            },
        )
    )
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)

    kinds = {type(e) for e in added}
    assert kinds == {VafabMiljoPickupSensor, VafabMiljoInvoiceSensor, VafabMiljoContractFeeSensor}


async def test_setup_skips_contract_sensor_without_a_fee():
    entry = _entry()
    entry.runtime_data = _coordinator(
        VafabMiljoData(
            pickups=[],
            authenticated=True,
            invoices={"data": []},
            sanitation={"contracts": [{"id": 1, "description": "No fee here", "fee": {}}]},
        )
    )
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)

    assert not any(isinstance(e, VafabMiljoContractFeeSensor) for e in added)


def test_pickup_sensor_native_value():
    coordinator = _coordinator(
        VafabMiljoData(pickups=[{"bins": [{"type": "Restavfall", "pickup_date": "2026-07-13"}]}])
    )
    sensor = VafabMiljoPickupSensor(coordinator, _entry(), "Restavfall")
    assert sensor.native_value == date(2026, 7, 13)


def test_pickup_sensor_native_value_none_when_bin_type_missing():
    coordinator = _coordinator(VafabMiljoData(pickups=[{"bins": []}]))
    sensor = VafabMiljoPickupSensor(coordinator, _entry(), "Restavfall")
    assert sensor.native_value is None


def test_invoice_sensor_reports_latest_invoice():
    coordinator = _coordinator(
        VafabMiljoData(
            pickups=[],
            authenticated=True,
            invoices={
                "data": [
                    {
                        "item": {
                            "amount": 817,
                            "invoiceDate": "2026-05-01",
                            "invoiceExpirationDate": "2026-05-31",
                            "paymentStatus": "Helt betald",
                            "ocrNumber": "111111111",
                        }
                    },
                    {"item": {"amount": 808}},
                ]
            },
        )
    )
    sensor = VafabMiljoInvoiceSensor(coordinator, _entry())
    assert sensor.native_value == 817
    assert sensor.extra_state_attributes["invoice_count"] == 2
    assert sensor.extra_state_attributes["payment_status"] == "Helt betald"


def test_invoice_sensor_handles_no_invoices():
    coordinator = _coordinator(VafabMiljoData(pickups=[], authenticated=True, invoices={"data": []}))
    sensor = VafabMiljoInvoiceSensor(coordinator, _entry())
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_contract_fee_sensor_attributes_empty_when_contract_disappears():
    contract = {"id": 1, "description": "Fast avgift", "fee": {"price": 1234.56, "unit": "kr/år"}}
    coordinator = _coordinator(VafabMiljoData(pickups=[], authenticated=True, sanitation={"contracts": []}))
    sensor = VafabMiljoContractFeeSensor(coordinator, _entry(), contract)
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_contract_fee_sensor_uses_contract_unit():
    contract = {
        "id": 1,
        "description": "Fast avgift",
        "type": "FAST AVGIFT",
        "pickupsPerYear": 0,
        "fee": {"price": 1234.56, "unit": "kr/år"},
    }
    coordinator = _coordinator(VafabMiljoData(pickups=[], authenticated=True, sanitation={"contracts": [contract]}))
    sensor = VafabMiljoContractFeeSensor(coordinator, _entry(), contract)
    assert sensor.native_value == 1234.56
    assert sensor._attr_native_unit_of_measurement == "kr/år"
    assert sensor.extra_state_attributes["type"] == "FAST AVGIFT"
