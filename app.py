"""Flask application for a forward-chaining predictive-maintenance expert system."""

from __future__ import annotations

import argparse
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypedDict

from flask import Flask, jsonify, render_template, request


HDF_DELTA_T_MAX = 8.6
HDF_RPM_MAX = 1380
PWF_POWER_MIN = 3500
PWF_POWER_MAX = 9000
OSF_STRAIN_LIMITS = {"L": 11_000, "M": 12_000, "H": 13_000}
TWF_WEAR_MIN = 200


class SensorFacts(TypedDict):
    machine_id: str
    product_type: str
    air_temp: float
    process_temp: float
    rpm: float
    torque: float
    wear: float


class WorkingMemory(SensorFacts):
    delta_t: float
    power: float
    strain: float
    strain_limit: int


class TriggeredRule(TypedDict):
    id: str
    code: str
    action: str
    severity: str


@dataclass(frozen=True)
class ProductionRule:
    rule_id: str
    code: str
    condition: Callable[[WorkingMemory], bool]
    action: str
    severity: str


def _hdf_condition(facts: WorkingMemory) -> bool:
    return facts["delta_t"] < HDF_DELTA_T_MAX and facts["rpm"] < HDF_RPM_MAX


def _pwf_condition(facts: WorkingMemory) -> bool:
    return facts["power"] < PWF_POWER_MIN or facts["power"] > PWF_POWER_MAX


def _osf_condition(facts: WorkingMemory) -> bool:
    return facts["strain"] > facts["strain_limit"]


def _twf_condition(facts: WorkingMemory) -> bool:
    return facts["wear"] >= TWF_WEAR_MIN


PRODUCTION_RULES = (
    ProductionRule(
        "R1",
        "HDF",
        _hdf_condition,
        "Work Order korektif, prioritas Tinggi; periksa pendingin",
        "failure",
    ),
    ProductionRule(
        "R2",
        "PWF",
        _pwf_condition,
        "Work Order, prioritas Tinggi; periksa suplai daya dan beban",
        "failure",
    ),
    ProductionRule(
        "R3",
        "OSF",
        _osf_condition,
        "Work Order, prioritas Tinggi; kurangi beban dan ganti pahat",
        "failure",
    ),
    ProductionRule(
        "R4",
        "TWF-W",
        _twf_condition,
        "Work Order terjadwal, prioritas Sedang; ganti pahat",
        "warning",
    ),
)

app = Flask(__name__)


def _validate_sensor_input(data: dict[str, object]) -> SensorFacts:
    """Validate and normalize the sensor payload before adding it to working memory."""
    machine_id_value = data.get("machine_id", "M-001")
    if not isinstance(machine_id_value, str) or not machine_id_value.strip():
        raise ValueError("machine_id wajib berupa teks dan tidak boleh kosong.")
    machine_id = machine_id_value.strip()

    product_type_value = data.get("product_type")
    if not isinstance(product_type_value, str):
        raise ValueError("Tipe produk harus salah satu dari L, M, atau H.")
    product_type = product_type_value.strip().upper()
    if product_type not in OSF_STRAIN_LIMITS:
        raise ValueError("Tipe produk harus salah satu dari L, M, atau H.")

    numeric_fields = ("air_temp", "process_temp", "rpm", "torque", "wear")
    missing = [field for field in numeric_fields if field not in data or data[field] == ""]
    if missing:
        raise ValueError(f"Field wajib belum diisi: {', '.join(missing)}.")

    values: dict[str, float] = {}
    try:
        for field in numeric_fields:
            if isinstance(data[field], bool):
                raise ValueError
            values[field] = float(data[field])
    except (TypeError, ValueError):
        raise ValueError("Semua nilai sensor harus berupa angka.") from None

    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("Nilai sensor harus berupa angka finite.")
    if values["air_temp"] <= 0 or values["process_temp"] <= 0:
        raise ValueError("Suhu absolut harus lebih besar dari 0 K.")
    if values["rpm"] < 0 or values["torque"] < 0 or values["wear"] < 0:
        raise ValueError("RPM, torque, dan wear tidak boleh negatif.")

    return {
        "machine_id": machine_id,
        "product_type": product_type,
        "air_temp": values["air_temp"],
        "process_temp": values["process_temp"],
        "rpm": values["rpm"],
        "torque": values["torque"],
        "wear": values["wear"],
    }


def _derive_facts(sensor_facts: SensorFacts) -> WorkingMemory:
    """Apply D1-D3 and return all facts stored in the working memory."""
    return {
        **sensor_facts,
        "delta_t": round(sensor_facts["process_temp"] - sensor_facts["air_temp"], 1),
        "power": sensor_facts["torque"] * sensor_facts["rpm"] * (2 * math.pi / 60),
        "strain": sensor_facts["wear"] * sensor_facts["torque"],
        "strain_limit": OSF_STRAIN_LIMITS[sensor_facts["product_type"]],
    }


def create_work_order(
    machine_id: str,
    status: str,
    triggered_rules: list[TriggeredRule],
) -> dict[str, object]:
    """Create the ERP work-order payload for a non-normal diagnosis."""
    if status not in {"FAILURE", "WASPADA"}:
        raise ValueError("Work Order hanya dibuat untuk status FAILURE atau WASPADA.")

    priority = "TINGGI" if status == "FAILURE" else "SEDANG"
    return {
        "wo_id": f"WO-{uuid.uuid4().hex[:8].upper()}",
        "machine_id": machine_id,
        "priority": priority,
        "failure_modes": [rule["code"] for rule in triggered_rules],
        "recommended_actions": [rule["action"] for rule in triggered_rules],
    }


def _rule_trace(rule: ProductionRule, triggered: bool) -> dict[str, str | bool]:
    condition_text = {
        "HDF": "ΔT < 8.6 K AND RPM < 1380",
        "PWF": "Daya < 3500 W OR Daya > 9000 W",
        "OSF": "Strain > strain_limit",
        "TWF-W": "Wear >= 200 min",
    }[rule.code]
    return {
        "id": rule.rule_id,
        "code": rule.code,
        "rule": f"IF {condition_text} THEN {rule.code}",
        "explanation": rule.action,
        "triggered": triggered,
    }


def forward_chain_diagnose(sensor_data: dict[str, object]) -> dict[str, object]:
    """Run the two-cycle forward-chaining process and return an explainable result."""
    sensor_facts = _validate_sensor_input(sensor_data)
    working_memory = _derive_facts(sensor_facts)

    reasoning_trace: list[dict[str, str | bool]] = [
        {
            "id": "F1",
            "rule": f"product_type = {working_memory['product_type']}",
            "explanation": "Fakta input: tipe produk.",
        },
        {
            "id": "F2",
            "rule": f"air_temp = {working_memory['air_temp']} K",
            "explanation": "Fakta input: suhu udara.",
        },
        {
            "id": "F3",
            "rule": f"process_temp = {working_memory['process_temp']} K",
            "explanation": "Fakta input: suhu proses.",
        },
        {
            "id": "F4",
            "rule": f"rpm = {working_memory['rpm']} rpm",
            "explanation": "Fakta input: kecepatan putar.",
        },
        {
            "id": "F5",
            "rule": f"torque = {working_memory['torque']} Nm",
            "explanation": "Fakta input: torsi.",
        },
        {
            "id": "F6",
            "rule": f"wear = {working_memory['wear']} min",
            "explanation": "Fakta input: keausan pahat.",
        },
        {
            "id": "D1",
            "rule": (
                "delta_t = round(process_temp - air_temp, 1) "
                f"= {working_memory['delta_t']:.1f} K"
            ),
            "explanation": "Fakta turunan F7 dimasukkan ke working memory.",
        },
        {
            "id": "D2",
            "rule": (
                "power = torque × rpm × (2π/60) "
                f"= {working_memory['power']:.2f} W"
            ),
            "explanation": "Fakta turunan F8 dimasukkan ke working memory.",
        },
        {
            "id": "D3",
            "rule": (
                f"strain = wear × torque = {working_memory['strain']:.2f}; "
                f"strain_limit = {working_memory['strain_limit']}"
            ),
            "explanation": "Fakta turunan F9 dan ambang tipe produk dimasukkan ke working memory.",
        },
    ]

    triggered_rules: list[TriggeredRule] = []
    for rule in PRODUCTION_RULES:
        triggered = rule.condition(working_memory)
        if triggered:
            triggered_rules.append(
                {
                    "id": rule.rule_id,
                    "code": rule.code,
                    "action": rule.action,
                    "severity": rule.severity,
                }
            )
        reasoning_trace.append(_rule_trace(rule, triggered))

    failure_modes = [
        rule["code"] for rule in triggered_rules if rule["severity"] == "failure"
    ]
    if failure_modes:
        status = "FAILURE"
    elif triggered_rules:
        status = "WASPADA"
    else:
        status = "NORMAL"

    recommendations = [rule["action"] for rule in triggered_rules]
    if not recommendations:
        recommendations = ["Lanjutkan operasi normal dan pemantauan sensor berkala."]

    reasoning_trace.append(
        {
            "id": "R5",
            "rule": f"Agregasi diagnosis → {status}",
            "explanation": (
                "Satu atau lebih aturan R1–R3 terpicu."
                if failure_modes
                else "Hanya aturan peringatan R4 yang terpicu."
                if triggered_rules
                else "Tidak ada aturan R1–R4 yang terpicu."
            ),
        }
    )

    work_order = (
        create_work_order(sensor_facts["machine_id"], status, triggered_rules)
        if status != "NORMAL"
        else None
    )
    return {
        "status": status,
        "status_label": status,
        "machine_id": sensor_facts["machine_id"],
        "input_facts": sensor_facts,
        "facts": {
            "delta_t": working_memory["delta_t"],
            "power": working_memory["power"],
            "strain": working_memory["strain"],
            "strain_limit": working_memory["strain_limit"],
        },
        "failure_modes": failure_modes,
        "triggered_rules": triggered_rules,
        "recommendations": recommendations,
        "reasoning_trace": reasoning_trace,
        "work_order": work_order,
    }


@app.get("/")
def index():
    """Render the interactive diagnosis dashboard."""
    return render_template("index.html")


@app.post("/api/diagnose")
def diagnose_api():
    """Accept sensor readings and return a transparent forward-chaining result."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request harus berisi JSON object."}), 400
    try:
        return jsonify(forward_chain_diagnose(data))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


def evaluate_dataset(csv_path: str | Path) -> tuple[int, dict[str, int], dict[str, float]]:
    """Evaluate the rules against the AI4I labels using pandas in CLI mode only."""
    import pandas as pd

    dataset = pd.read_csv(csv_path, encoding="utf-8-sig")
    required_columns = {
        "UDI",
        "Type",
        "Air temperature [K]",
        "Process temperature [K]",
        "Rotational speed [rpm]",
        "Torque [Nm]",
        "Tool wear [min]",
        "Machine failure",
    }
    missing_columns = required_columns.difference(dataset.columns)
    if missing_columns:
        raise ValueError(f"Kolom dataset tidak ditemukan: {', '.join(sorted(missing_columns))}.")
    if dataset.empty:
        raise ValueError("Dataset tidak memiliki baris data.")

    counts = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
    columns = [
        "UDI",
        "Type",
        "Air temperature [K]",
        "Process temperature [K]",
        "Rotational speed [rpm]",
        "Torque [Nm]",
        "Tool wear [min]",
        "Machine failure",
    ]
    for row_number, row in enumerate(dataset[columns].itertuples(index=False, name=None), start=2):
        udi, product_type, air_temp, process_temp, rpm, torque, wear, label = row
        try:
            diagnosis = forward_chain_diagnose(
                {
                    "machine_id": f"UDI-{udi}",
                    "product_type": product_type,
                    "air_temp": air_temp,
                    "process_temp": process_temp,
                    "rpm": rpm,
                    "torque": torque,
                    "wear": wear,
                }
            )
            actual_value = int(label)
            if actual_value not in (0, 1):
                raise ValueError("Machine failure harus bernilai 0 atau 1.")
            actual = actual_value == 1
            predicted = bool(diagnosis["failure_modes"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"Baris {row_number} tidak valid: {error}") from error

        if predicted and actual:
            counts["TP"] += 1
        elif predicted:
            counts["FP"] += 1
        elif actual:
            counts["FN"] += 1
        else:
            counts["TN"] += 1

    total = len(dataset)
    tp, fp, tn, fn = counts["TP"], counts["FP"], counts["TN"], counts["FN"]
    metrics = {
        "accuracy": (tp + tn) / total,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "f1_score": (2 * tp / (2 * tp + fp + fn)) if 2 * tp + fp + fn else 0.0,
    }
    return total, counts, metrics


def main() -> None:
    """Start the Flask server or run the optional command-line evaluation."""
    parser = argparse.ArgumentParser(description="AI4I 2020 predictive-maintenance expert system")
    parser.add_argument(
        "--evaluate",
        metavar="CSV",
        help="evaluate the rule engine against an AI4I 2020 CSV dataset",
    )
    args = parser.parse_args()

    if args.evaluate:
        try:
            total, counts, metrics = evaluate_dataset(args.evaluate)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print(f"Baris dievaluasi : {total:,}")
        print("Confusion Matrix (baris = aktual, kolom = prediksi)")
        print(f"{'':<23}{'Normal':>12}{'Failure':>12}")
        print(f"{'Aktual Normal':<23}{counts['TN']:>12,}{counts['FP']:>12,}")
        print(f"{'Aktual Failure':<23}{counts['FN']:>12,}{counts['TP']:>12,}")
        print(
            "Jumlah kelas positif: "
            f"TP={counts['TP']:,}  FP={counts['FP']:,}  "
            f"FN={counts['FN']:,}  TN={counts['TN']:,}"
        )
        print("Metrik (kelas positif: Machine failure)")
        metric_labels = {
            "accuracy": "Akurasi",
            "precision": "Presisi",
            "recall": "Recall",
            "f1_score": "F1-score",
        }
        for name, value in metrics.items():
            print(f"  {metric_labels[name]:<10}: {value * 100:6.2f}%")
        print("Prediksi kegagalan memakai aturan HDF, PWF, dan OSF; TWF-W adalah peringatan.")
        return

    app.run(debug=True)


if __name__ == "__main__":
    main()
