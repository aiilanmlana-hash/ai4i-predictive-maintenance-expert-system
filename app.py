"""Flask application for a forward-chaining predictive-maintenance prototype."""

import argparse
import csv
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request


# Dataset-derived thresholds for the AI4I 2020 failure modes.
HDF_DELTA_T_MAX = 8.6
HDF_RPM_MAX = 1380
PWF_POWER_MIN = 3500
PWF_POWER_MAX = 9000
OSF_STRAIN_LIMITS = {"L": 11_000, "M": 12_000, "H": 13_000}
TWF_WEAR_MIN = 200

app = Flask(__name__)


def create_work_order(priority, reasons):
    """Create an in-memory ERP work order for the diagnosis result."""
    return {
        "work_order_id": f"WO-{uuid.uuid4().hex[:8].upper()}",
        "priority": priority,
        "status": "OPEN",
        "description": "; ".join(reasons),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system": "ERP simulation",
    }


def _validate_sensor_input(data):
    """Parse and validate the sensor values received from the UI or API."""
    required = ("air_temp", "process_temp", "rpm", "torque", "tool_wear")
    missing = [field for field in required if field not in data or data[field] == ""]
    if missing:
        raise ValueError(f"Field wajib belum diisi: {', '.join(missing)}.")

    try:
        values = {field: float(data[field]) for field in required}
    except (TypeError, ValueError):
        raise ValueError("Semua nilai sensor harus berupa angka.") from None

    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("Nilai sensor harus berupa angka finite.")
    if values["air_temp"] <= 0 or values["process_temp"] <= 0:
        raise ValueError("Suhu absolut harus lebih besar dari 0 K.")
    if values["rpm"] < 0 or values["torque"] < 0 or values["tool_wear"] < 0:
        raise ValueError("RPM, torque, dan tool wear tidak boleh negatif.")

    product_type = str(data.get("product_type", "")).strip().upper()
    if product_type not in OSF_STRAIN_LIMITS:
        raise ValueError("Tipe produk harus salah satu dari L, M, atau H.")

    return {**values, "product_type": product_type}


def forward_chain_diagnose(sensor_data):
    """Run two-level forward chaining and return facts, diagnosis, and explanation."""
    sensors = _validate_sensor_input(sensor_data)

    # Level 1: derive facts from the sensor readings, then evaluate rule antecedents.
    delta_t = sensors["process_temp"] - sensors["air_temp"]
    power = sensors["torque"] * sensors["rpm"] * (2 * math.pi / 60)
    strain = sensors["tool_wear"] * sensors["torque"]

    fired_rules = []
    rule_conditions = {
        "R1": delta_t < HDF_DELTA_T_MAX and sensors["rpm"] < HDF_RPM_MAX,
        "R2": power < PWF_POWER_MIN or power > PWF_POWER_MAX,
        "R3": strain >= OSF_STRAIN_LIMITS[sensors["product_type"]],
        "R4": sensors["tool_wear"] >= TWF_WEAR_MIN,
    }
    rule_descriptions = {
        "R1": (
            "HDF: ΔT < 8,6 K dan RPM < 1.380 rpm.",
            "Selisih suhu rendah bersamaan dengan putaran lambat; periksa sistem pendinginan.",
        ),
        "R2": (
            "PWF: daya < 3.500 W atau > 9.000 W.",
            "Daya berada di luar rentang operasi; periksa beban, torque, dan motor.",
        ),
        "R3": (
            f"OSF: strain ≥ {OSF_STRAIN_LIMITS[sensors['product_type']]:,} untuk tipe {sensors['product_type']}.",
            "Beban akumulatif tool wear tinggi; inspeksi dan jadwalkan penggantian alat.",
        ),
        "R4": (
            f"Peringatan TWF: tool wear ≥ {TWF_WEAR_MIN} menit.",
            "Tool wear mencapai ambang TWF dataset; jadwalkan inspeksi/penggantian alat.",
        ),
    }
    for rule_id, condition in rule_conditions.items():
        if condition:
            title, explanation = rule_descriptions[rule_id]
            fired_rules.append({"id": rule_id, "rule": title, "explanation": explanation})

    # Level 2: aggregate inferred facts into status, actions, and an ERP simulation.
    failure_modes = [rule_id for rule_id in ("R1", "R2", "R3") if rule_conditions[rule_id]]
    twf_warning = rule_conditions["R4"]
    if failure_modes:
        status = "FAILURE"
        status_label = "FAILURE"
        priority = "URGENT"
    elif twf_warning:
        status = "WARNING"
        status_label = "WASPADA"
        priority = "HIGH"
    else:
        status = "NORMAL"
        status_label = "NORMAL"
        priority = None

    recommendations = [
        item["explanation"]
        for item in fired_rules
    ] or ["Lanjutkan operasi normal dan pemantauan sensor berkala."]
    work_order = create_work_order(priority, recommendations) if priority else None
    reasoning_trace = [
        {
            "id": "F1",
            "rule": f"ΔT = process_temp − air_temp = {delta_t:.2f} K",
            "explanation": "Fakta turunan selisih suhu.",
        },
        {
            "id": "F2",
            "rule": f"Daya = torque × RPM × 2π/60 = {power:.2f} W",
            "explanation": "Fakta turunan daya mekanis.",
        },
        {
            "id": "F3",
            "rule": f"Strain = tool_wear × torque = {strain:.2f}",
            "explanation": "Fakta turunan beban akumulatif keausan.",
        },
        *fired_rules,
        {
            "id": "R5",
            "rule": f"Agregasi diagnosis → {status_label}",
            "explanation": (
                "R1–R3 menunjukkan indikasi kegagalan."
                if failure_modes
                else "R4 menghasilkan peringatan pemeliharaan."
                if twf_warning
                else "Tidak ada aturan kegagalan atau peringatan yang terpicu."
            ),
        },
    ]

    return {
        "status": status,
        "status_label": status_label,
        "facts": {
            "delta_t": round(delta_t, 2),
            "power": round(power, 2),
            "strain": round(strain, 2),
            "osf_strain_limit": OSF_STRAIN_LIMITS[sensors["product_type"]],
        },
        "triggered_rules": fired_rules,
        "failure_modes": failure_modes,
        "twf_warning": twf_warning,
        "recommendations": recommendations,
        "work_order": work_order,
        "reasoning_trace": reasoning_trace,
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


def evaluate_dataset(csv_path):
    """Evaluate binary failure predictions against the AI4I Machine failure label."""
    counts = {"TP": 0, "FP": 0, "TN": 0, "FN": 0}
    total = 0
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as dataset:
        reader = csv.DictReader(dataset)
        required_columns = {
            "Type",
            "Air temperature [K]",
            "Process temperature [K]",
            "Rotational speed [rpm]",
            "Torque [Nm]",
            "Tool wear [min]",
            "Machine failure",
        }
        missing_columns = required_columns.difference(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(f"Kolom dataset tidak ditemukan: {', '.join(sorted(missing_columns))}.")

        for row_number, row in enumerate(reader, start=2):
            try:
                diagnosis = forward_chain_diagnose(
                    {
                        "product_type": row["Type"],
                        "air_temp": row["Air temperature [K]"],
                        "process_temp": row["Process temperature [K]"],
                        "rpm": row["Rotational speed [rpm]"],
                        "torque": row["Torque [Nm]"],
                        "tool_wear": row["Tool wear [min]"],
                    }
                )
                actual = int(row["Machine failure"]) == 1
                # Only R1–R3 count as predicted failures; R4 is an advisory warning.
                predicted = bool(diagnosis["failure_modes"])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"Baris {row_number} tidak valid: {error}") from error

            total += 1
            if predicted and actual:
                counts["TP"] += 1
            elif predicted:
                counts["FP"] += 1
            elif actual:
                counts["FN"] += 1
            else:
                counts["TN"] += 1

    if total == 0:
        raise ValueError("Dataset tidak memiliki baris data.")

    tp, fp, tn, fn = counts["TP"], counts["FP"], counts["TN"], counts["FN"]
    metrics = {
        "accuracy": (tp + tn) / total,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "f1_score": (2 * tp / (2 * tp + fp + fn)) if 2 * tp + fp + fn else 0.0,
    }
    return total, counts, metrics


def main():
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
        print("Prediksi kegagalan memakai R1–R3; R4 (TWF) dicatat sebagai peringatan.")
        return

    app.run(debug=True)


if __name__ == "__main__":
    main()
