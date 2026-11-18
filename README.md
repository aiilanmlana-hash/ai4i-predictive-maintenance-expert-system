# Sistem Pakar Pemeliharaan Prediktif

Prototipe sistem pakar berbasis aturan (*rule-based*) untuk mendeteksi indikasi kegagalan mesin pabrik. Flask melayani dashboard dan REST API, sedangkan **pandas hanya dimuat saat evaluasi batch CLI**. Inferensi menggunakan forward chaining dua tingkat dan mensimulasikan Work Order MES/ERP.

## Sumber dataset publik

Dataset pengembangan dan evaluasi batch adalah **AI4I 2020 Predictive Maintenance Dataset**, disusun oleh Stephan Matzka dan dipublikasikan melalui [Kaggle](https://www.kaggle.com/datasets/stephanmatzka/predictive-maintenance-dataset-ai4i-2020). CSV yang disertakan memuat 10.000 rekaman simulasi mesin milling.

Atribut utama meliputi suhu udara dan proses, kecepatan putar, torque, tool wear, tipe produk, serta label kegagalan seperti TWF, HDF, PWF, OSF, dan RNF. Sistem prototipe ini menerapkan aturan untuk HDF, PWF, OSF, dan peringatan TWF; RNF tidak dimodelkan sebagai aturan diagnosis.

## Arsitektur sistem

1. **Input MES:** operator mengirim pembacaan sensor melalui dashboard atau endpoint `POST /api/diagnose`.
2. **Working memory:** input F1–F6 berisi tipe produk, suhu udara/proses, RPM, torque, dan wear pahat; ID mesin menyertai payload.
3. **Siklus derivasi:** D1 menghasilkan ΔT yang dibulatkan satu desimal, D2 menghitung daya mekanis, dan D3 menghitung strain serta ambang berdasarkan tipe produk.
4. **Siklus diagnosis:** R1–R4 dievaluasi independen. HDF, PWF, atau OSF menghasilkan `FAILURE`; hanya TWF-W menghasilkan `WASPADA`; tanpa aturan terpicu menghasilkan `NORMAL`. RNF tidak dimodelkan.
5. **Simulasi ERP:** diagnosis non-normal membuat Work Order simulasi in-memory berisi ID, mesin, prioritas, mode, dan tindakan. Ini bukan konektor ke ERP produksi.

## Tampilan antarmuka

Dashboard menggunakan palet Enterprise terang, permukaan putih, teks slate, dan border tipis. Warna status mengikuti makna operasional:

- **Normal:** hijau
- **Waspada:** amber
- **Failure:** merah

## Instalasi dan cara menjalankan

Pastikan Python 3 tersedia, lalu jalankan perintah berikut dari folder `Sistem Pakar`.

### Pasang dependensi

```bash
pip install -r requirements.txt
```

### Jalankan web server

```bash
python app.py
```

Buka `http://127.0.0.1:5000` pada browser.

### Evaluasi batch melalui CLI

```bash
python app.py --evaluate ai4i2020.csv
```

CLI memuat pandas secara lokal pada fungsi evaluasi, lalu mencetak confusion matrix, TP, FP, FN, TN, akurasi, presisi, recall, dan F1-score berdasarkan kolom `Machine failure`. Prediksi kegagalan biner memakai HDF, PWF, dan OSF; TWF-W adalah peringatan dan tidak dihitung sebagai kegagalan.

## API diagnosis

Endpoint `POST /api/diagnose` menerima JSON berisi `machine_id` (opsional, default `M-001`), `product_type` (`L`, `M`, atau `H`), `air_temp`, `process_temp`, `rpm`, `torque`, dan `wear`. Respons mencakup fakta input/turunan, status, mode serta aturan yang terpicu, tindakan, jejak penalaran, dan Work Order non-normal dengan `wo_id`, `machine_id`, `priority`, `failure_modes`, dan `recommended_actions`.

## Aturan inferensi

- **D1:** `delta_t = round(process_temp - air_temp, 1)`.
- **D2:** `power = torque × rpm × (2π/60)`.
- **D3:** `strain = wear × torque`; batas strain adalah 11.000 (L), 12.000 (M), dan 13.000 (H).
- **R1 — HDF:** ΔT < 8,6 K dan RPM < 1.380.
- **R2 — PWF:** daya mekanis < 3.500 W atau > 9.000 W.
- **R3 — OSF:** `strain > strain_limit` (perbandingan strict).
- **R4 — TWF-W:** wear ≥ 200 menit. R4 saja menghasilkan status WASPADA.
- R1–R3 yang terpicu menghasilkan FAILURE; R4 saja menghasilkan WASPADA; tanpa aturan terpicu menghasilkan NORMAL.

## Deployment Vercel

`vercel.json` mengarahkan request ke aplikasi Flask global `app` menggunakan runtime `@vercel/python`. Instal dependensi dari `requirements.txt` saat proses build/deploy.
