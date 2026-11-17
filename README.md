# Sistem Pakar Pemeliharaan Prediktif

Prototipe aplikasi internal untuk diagnosis kondisi mesin menggunakan dataset AI4I 2020. Backend Flask menyediakan antarmuka web dan endpoint REST; aturan forward chaining menghasilkan diagnosis yang dapat ditelusuri operator.

## Arsitektur ringkas

1. **Input MES:** operator mengirim suhu udara/proses, RPM, torque, tool wear, dan tipe produk melalui dashboard atau `POST /api/diagnose`.
2. **Forward chaining tingkat 1:** sistem menurunkan fakta ΔT, daya mekanis, dan strain, lalu mengevaluasi aturan HDF (R1), PWF (R2), OSF (R3), dan peringatan TWF (R4).
3. **Forward chaining tingkat 2:** hasil aturan diagregasi menjadi `NORMAL`, `WASPADA`, atau `FAILURE`. UI menampilkan fakta, rekomendasi, serta jejak aturan yang terpicu.
4. **Simulasi ERP:** status selain normal membuat Work Order simulasi in-memory. Ini demonstrasi integrasi alur MES/ERP, bukan konektor ERP produksi.
5. **Evaluasi offline:** mode CLI membandingkan hasil aturan terhadap label `Machine failure` di CSV dan mencetak confusion matrix serta metrik klasifikasi.

## Instalasi dan menjalankan

Pastikan Python 3 tersedia, lalu jalankan dari folder proyek:

```bash
pip install -r requirements.txt
```

Jalankan web server:

```bash
python app.py
```

Buka `http://127.0.0.1:5000`. Endpoint JSON `POST /api/diagnose` menerima `air_temp`, `process_temp`, `rpm`, `torque`, `tool_wear`, dan `product_type` (`L`, `M`, atau `H`).

## Aturan inferensi

- **R1 — HDF:** ΔT < 8,6 K dan RPM < 1.380.
- **R2 — PWF:** daya mekanis < 3.500 W atau > 9.000 W.
- **R3 — OSF:** `tool_wear × torque` ≥ 11.000 (L), 12.000 (M), atau 13.000 (H).
- **R4 — Peringatan TWF:** tool wear ≥ 200 menit. R4 menghasilkan peringatan WASPADA, bukan kegagalan terkonfirmasi.
- Hasil level kedua: R1–R3 menghasilkan FAILURE; R4 saja menghasilkan WASPADA; selain itu NORMAL.

## Evaluasi dataset

Jalankan evaluasi CLI terhadap dataset yang disertakan:

```bash
python app.py --evaluate ai4i2020.csv
```

Confusion matrix dan akurasi, presisi, recall, serta F1-score dihitung terhadap kolom `Machine failure`. Untuk klasifikasi biner evaluasi, hanya R1–R3 yang dihitung sebagai prediksi kegagalan; R4 tetap peringatan advisori.

Dataset pada `ai4i2020.csv` mengikuti AI4I 2020 Predictive Maintenance Dataset dari UCI Machine Learning Repository, yang juga menjadi sumber dataset Kaggle pada studi kasus.
