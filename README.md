# Sistem Pakar Pemeliharaan Prediktif

Prototipe sistem pakar berbasis aturan (*rule-based*) untuk membantu mendeteksi indikasi kegagalan mesin pabrik. Sistem menggunakan inferensi **forward chaining dua tingkat** untuk mengolah data sensor dan menyiapkan simulasi perintah kerja pada alur MES/ERP.

## Sumber dataset publik

Dataset pengembangan dan evaluasi batch adalah **AI4I 2020 Predictive Maintenance Dataset**, disusun oleh Stephan Matzka dan dipublikasikan melalui [Kaggle](https://www.kaggle.com/datasets/stephanmatzka/predictive-maintenance-dataset-ai4i-2020). CSV yang disertakan memuat 10.000 rekaman simulasi mesin milling.

Atribut utama meliputi suhu udara dan proses, kecepatan putar, torque, tool wear, tipe produk, serta label kegagalan seperti TWF, HDF, PWF, OSF, dan RNF. Sistem prototipe ini menerapkan aturan untuk HDF, PWF, OSF, dan peringatan TWF; RNF tidak dimodelkan sebagai aturan diagnosis.

## Arsitektur sistem

1. **Input MES:** operator mengirim pembacaan sensor melalui dashboard atau endpoint `POST /api/diagnose`.
2. **Forward chaining tingkat 1:** sistem menurunkan fakta ΔT, daya mekanis, dan strain, lalu mengevaluasi aturan HDF (R1), PWF (R2), OSF (R3), dan peringatan TWF (R4).
3. **Forward chaining tingkat 2:** hasil aturan diagregasi menjadi `NORMAL`, `WASPADA`, atau `FAILURE`. Dashboard menyajikan fakta, rekomendasi tindakan, dan jejak aturan.
4. **Simulasi ERP:** diagnosis selain normal membuat Work Order simulasi in-memory. Ini demonstrasi alur integrasi MES/ERP, bukan konektor ke sistem ERP produksi.

## Tampilan antarmuka

Dashboard menggunakan palet **Modern Slate** dengan permukaan slate dingin, teks grafit, dan aksen steel-blue. Warna status mengikuti makna operasional:

- **Normal:** hijau sage (`#496b57`)
- **Waspada / Warning:** kuning mustard (`#80621e`)
- **Failure:** merah bata (`#93483f`)

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

CLI mencetak confusion matrix, TP, FP, FN, TN, akurasi, presisi, recall, dan F1-score berdasarkan kolom `Machine failure`. Prediksi kegagalan biner menggunakan R1–R3; R4 merupakan peringatan TWF advisori dan tidak dihitung sebagai kegagalan pasti.

## API diagnosis

Endpoint `POST /api/diagnose` menerima JSON dengan field `air_temp`, `process_temp`, `rpm`, `torque`, `tool_wear`, dan `product_type` (`L`, `M`, atau `H`). Respons memuat status, fakta turunan, rekomendasi, Work Order simulasi (jika diperlukan), dan jejak penalaran.

## Aturan inferensi

- **R1 — HDF:** ΔT < 8,6 K dan RPM < 1.380.
- **R2 — PWF:** daya mekanis < 3.500 W atau > 9.000 W.
- **R3 — OSF:** `tool_wear × torque` ≥ 11.000 (L), 12.000 (M), atau 13.000 (H).
- **R4 — Peringatan TWF:** tool wear ≥ 200 menit. R4 saja menghasilkan status WASPADA, bukan kegagalan terkonfirmasi.
- Hasil level kedua: R1–R3 menghasilkan FAILURE; R4 saja menghasilkan WASPADA; selain itu NORMAL.
