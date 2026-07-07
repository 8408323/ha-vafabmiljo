"""Tests for VafabMiljö sensor entities."""

from __future__ import annotations

from datetime import date
from unittest.mock import Mock

from homeassistant.config_entries import ConfigEntry
from vafabmiljo.coordinator import VafabMiljoData
from vafabmiljo.sensor import (
    VafabMiljoAvailableComplaintsSensor,
    VafabMiljoAvailableOrdersSensor,
    VafabMiljoContractFeeSensor,
    VafabMiljoInvoiceSensor,
    VafabMiljoPickupSensor,
    VafabMiljoPropertySensor,
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
            invoices={"data": [{"item": {"amount": 500}}]},
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


async def test_setup_adds_property_sensor_when_properties_present():
    entry = _entry()
    entry.runtime_data = _coordinator(
        VafabMiljoData(
            pickups=[],
            authenticated=True,
            invoices={"data": []},
            properties={"current": {"id": 1, "designation": "Testgatan 2:7"}},
        )
    )
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)

    assert any(isinstance(e, VafabMiljoPropertySensor) for e in added)


async def test_setup_adds_orders_and_complaints_sensors_when_available():
    entry = _entry()
    entry.runtime_data = _coordinator(
        VafabMiljoData(
            pickups=[],
            authenticated=True,
            invoices={"data": []},
            parameters={"ordersAvailable": True, "complaintsAvailable": True},
        )
    )
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)

    kinds = {type(e) for e in added}
    assert VafabMiljoAvailableOrdersSensor in kinds
    assert VafabMiljoAvailableComplaintsSensor in kinds


async def test_setup_skips_orders_and_complaints_sensors_when_unavailable():
    entry = _entry()
    entry.runtime_data = _coordinator(
        VafabMiljoData(
            pickups=[],
            authenticated=True,
            invoices={"data": []},
            parameters={"ordersAvailable": False, "complaintsAvailable": False},
        )
    )
    added: list = []
    await async_setup_entry(hass=None, entry=entry, async_add_entities=added.extend)

    kinds = {type(e) for e in added}
    assert VafabMiljoAvailableOrdersSensor not in kinds
    assert VafabMiljoAvailableComplaintsSensor not in kinds


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
                            "amount": 500,
                            "invoiceDate": "2026-01-01",
                            "invoiceExpirationDate": "2026-01-31",
                            "paymentStatus": "Helt betald",
                            "ocrNumber": "111111111",
                        }
                    },
                    {"item": {"amount": 450}},
                ]
            },
        )
    )
    sensor = VafabMiljoInvoiceSensor(coordinator, _entry())
    assert sensor.native_value == 500
    assert sensor.extra_state_attributes["invoice_count"] == 2
    assert sensor.extra_state_attributes["payment_status"] == "Helt betald"
    invoices = sensor.extra_state_attributes["invoices"]
    assert len(invoices) == 2
    assert invoices[0] == {
        "id": None,
        "amount": 500,
        "invoice_date": "2026-01-01",
        "due_date": "2026-01-31",
        "payment_status": "Helt betald",
        "ocr_number": "111111111",
    }
    assert invoices[1]["amount"] == 450


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


def test_property_sensor_reports_designation_and_attributes():
    coordinator = _coordinator(
        VafabMiljoData(
            pickups=[],
            authenticated=True,
            properties={
                "current": {
                    "id": 1,
                    "designation": "Testgatan 2:7",
                    "zip": "72596",
                    "services": ["RH"],
                    "environment": "default",
                }
            },
        )
    )
    sensor = VafabMiljoPropertySensor(coordinator, _entry())
    assert sensor.native_value == "Testgatan 2:7"
    assert sensor.extra_state_attributes == {"zip": "72596", "services": ["RH"], "environment": "default"}


def test_property_sensor_handles_missing_properties():
    coordinator = _coordinator(VafabMiljoData(pickups=[], authenticated=True, properties=None))
    sensor = VafabMiljoPropertySensor(coordinator, _entry())
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {}


def test_available_orders_sensor_reports_count_and_titles():
    coordinator = _coordinator(
        VafabMiljoData(
            pickups=[],
            authenticated=True,
            properties={"current": {"id": 1}},
            orders={"1": {"10": [{"id": 719, "title": "Budning"}]}},
        )
    )
    sensor = VafabMiljoAvailableOrdersSensor(coordinator, _entry())
    assert sensor.native_value == 1
    assert sensor.extra_state_attributes == {"titles": ["Budning"]}


def test_available_complaints_sensor_reports_count_and_descriptions():
    coordinator = _coordinator(
        VafabMiljoData(
            pickups=[],
            authenticated=True,
            properties={"current": {"id": 1}},
            complaints={"1": {"10": [{"description": "Utebliven hämtning"}]}},
        )
    )
    sensor = VafabMiljoAvailableComplaintsSensor(coordinator, _entry())
    assert sensor.native_value == 1
    assert sensor.extra_state_attributes == {"descriptions": ["Utebliven hämtning"]}
