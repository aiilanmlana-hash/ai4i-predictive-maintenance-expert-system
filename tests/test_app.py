import math
import unittest

from app import PRODUCTION_RULES, app, forward_chain_diagnose


def sensor_data(**updates):
    values = {
        "machine_id": "M-001",
        "product_type": "M",
        "air_temp": 298.1,
        "process_temp": 308.6,
        "rpm": 1500,
        "torque": 40,
        "wear": 100,
    }
    return {**values, **updates}


class ForwardChainingTests(unittest.TestCase):
    def test_derives_rounded_temperature_power_and_strain(self):
        result = forward_chain_diagnose(sensor_data(process_temp=308.64))

        self.assertEqual(result["facts"]["delta_t"], 10.5)
        self.assertAlmostEqual(result["facts"]["power"], 40 * 1500 * (2 * math.pi / 60))
        self.assertEqual(result["facts"]["strain"], 4000)
        self.assertEqual(result["facts"]["strain_limit"], 12000)

    def test_hdf_uses_strict_delta_and_rpm_limits(self):
        delta_boundary = forward_chain_diagnose(
            sensor_data(air_temp=298.0, process_temp=306.6, rpm=1379)
        )
        rpm_boundary = forward_chain_diagnose(
            sensor_data(air_temp=298.0, process_temp=306.5, rpm=1380)
        )
        below_both = forward_chain_diagnose(
            sensor_data(air_temp=298.0, process_temp=306.4, rpm=1379)
        )

        self.assertEqual(delta_boundary["status"], "NORMAL")
        self.assertEqual(rpm_boundary["status"], "NORMAL")
        self.assertEqual(below_both["failure_modes"], ["HDF"])

    def test_pwf_uses_strict_power_limits(self):
        power_rule = next(rule for rule in PRODUCTION_RULES if rule.code == "PWF")
        facts = {
            "machine_id": "M-001",
            "product_type": "M",
            "air_temp": 298.0,
            "process_temp": 308.0,
            "rpm": 60.0,
            "torque": 40.0,
            "wear": 100.0,
            "delta_t": 10.0,
            "power": 3500.0,
            "strain": 4000.0,
            "strain_limit": 12000,
        }

        self.assertFalse(power_rule.condition({**facts, "power": 3500.0}))
        self.assertFalse(power_rule.condition({**facts, "power": 9000.0}))
        self.assertTrue(power_rule.condition({**facts, "power": 3499.9}))
        self.assertTrue(power_rule.condition({**facts, "power": 9000.1}))

    def test_osf_requires_strain_strictly_over_product_limit(self):
        at_limit = forward_chain_diagnose(
            sensor_data(rpm=500, torque=80, wear=150)
        )
        above_limit = forward_chain_diagnose(
            sensor_data(rpm=500, torque=80, wear=150.01)
        )

        self.assertEqual(at_limit["status"], "NORMAL")
        self.assertEqual(above_limit["failure_modes"], ["OSF"])

    def test_twf_warning_creates_scheduled_work_order(self):
        result = forward_chain_diagnose(sensor_data(wear=200))

        self.assertEqual(result["status"], "WASPADA")
        self.assertEqual(result["failure_modes"], [])
        self.assertEqual(
            result["triggered_rules"][0]["code"],
            "TWF-W",
        )
        self.assertEqual(
            result["work_order"]["priority"],
            "SEDANG",
        )
        self.assertEqual(
            set(result["work_order"]),
            {"wo_id", "machine_id", "priority", "failure_modes", "recommended_actions"},
        )
        self.assertEqual(result["work_order"]["machine_id"], "M-001")
        self.assertEqual(
            result["work_order"]["failure_modes"],
            ["TWF-W"],
        )
        self.assertEqual(
            result["work_order"]["recommended_actions"],
            ["Work Order terjadwal, prioritas Sedang; ganti pahat"],
        )

    def test_failure_takes_precedence_over_twf_warning(self):
        result = forward_chain_diagnose(
            sensor_data(rpm=1379, air_temp=298.0, process_temp=306.4, wear=200)
        )

        self.assertEqual(result["status"], "FAILURE")
        self.assertEqual(result["failure_modes"], ["HDF"])
        self.assertEqual(result["work_order"]["priority"], "TINGGI")
        self.assertEqual(result["work_order"]["failure_modes"], ["HDF", "TWF-W"])

    def test_api_accepts_specified_payload_and_defaults_machine_id(self):
        client = app.test_client()
        response = client.post(
            "/api/diagnose",
            json={
                "product_type": "M",
                "air_temp": 298.1,
                "process_temp": 308.6,
                "rpm": 1500,
                "torque": 40,
                "wear": 100,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["machine_id"], "M-001")
        self.assertEqual(payload["status"], "NORMAL")
        self.assertIsNone(payload["work_order"])


if __name__ == "__main__":
    unittest.main()
