# Meguyomi

Meguyomi adalah proyek aplikasi web privat untuk menerjemahkan manga dalam
format PDF dari bahasa Jepang atau Mandarin ke bahasa Indonesia. Alur MVP yang
direncanakan meliputi login, upload PDF, pemrosesan terjemahan di latar belakang,
pratinjau, dan download PDF hasil terjemahan.

Fondasi aplikasi sudah menyediakan Next.js, FastAPI, Celery, PostgreSQL, Redis,
Docker Compose, login privat satu akun, UI dan API upload/riwayat PDF, worker
preview, service `local-ai` untuk OCR Jepang/Mandarin dan terjemahan NLLB lokal,
translation memory PostgreSQL, penyusunan PDF hasil, dan download privat.
Penggantian teks masih menggunakan kompositor MVP: kotak sumber dipisahkan dari
area penempatan, teks sumber dibersihkan sebelum teks Indonesia ditata, dan SFX
hanya diganti di tempat ketika mask teks sumber dapat dibuat dengan aman.

Task retry dan watchdog berjalan pada worker maintenance terpisah agar tetap
aktif ketika worker terjemahan sedang memproses bab panjang.

## Struktur proyek

- `frontend/` — aplikasi web Next.js dan aset publik.
- `backend/app/api/` — endpoint HTTP FastAPI.
- `backend/app/core/` — konfigurasi dan utilitas inti backend.
- `backend/app/db/` — koneksi dan sesi database.
- `backend/alembic/` — migrasi skema database.
- `backend/app/models/` — model database.
- `backend/app/schemas/` — schema request dan response.
- `backend/app/services/` — pipeline PDF, OCR, terjemahan, dan penyusunan hasil.
- `backend/app/tasks/` — job pemrosesan latar belakang.
- `backend/tests/` — pengujian backend.
- `docs/` — dokumentasi produk dan teknis.
- `storage/` — file upload dan hasil pemrosesan lokal; isinya tidak dilacak Git.

## Menjalankan aplikasi

1. Salin `.env.example` menjadi `.env`, lalu ganti password database lokal.
   Tidak ada API key yang diperlukan.
2. Build image API untuk menyiapkan utilitas keamanan:

   ```powershell
   docker compose build api
   ```

3. Unduh model OCR dan NLLB sekali ke volume Docker lokal. Langkah ini
   membutuhkan koneksi internet; setelah selesai, inferensi berjalan offline:

   ```powershell
   docker compose build local-ai
   docker compose --profile setup run --rm model-setup
   ```

4. Buat hash Argon2 untuk password login dan salin hasilnya ke
   `ADMIN_PASSWORD_HASH`. Password dimasukkan melalui prompt dan tidak tampil di
   command history:

   ```powershell
   docker compose run --rm api python -m app.core.password_cli
   ```

5. Buat session secret dan salin hasilnya ke `SESSION_SECRET`:

   ```powershell
   docker compose run --rm api python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

6. Jalankan seluruh layanan:

   ```powershell
   docker compose up --build
   ```

7. Buka frontend di `http://localhost:3000` dan dokumentasi API di
   `http://localhost:8000/docs`.

Image dan model membutuhkan beberapa GB ruang penyimpanan. Sediakan setidaknya
8 GB RAM untuk Docker; 12 GB atau lebih disarankan untuk pemasangan model.
Konfigurasi bawaan memakai CPU. Kecepatan dan kualitas perlu dinilai dengan
halaman manga kamu sendiri, terutama teks kecil, SFX, dan balon yang rumit.
Model NLLB bawaan berlisensi CC-BY-NC-4.0 untuk penggunaan nonkomersial.

Pilihan awal bahasa sumber saat upload adalah **Deteksi otomatis**. Pilihan manual
**Jepang**, **Mandarin (sederhana)**, dan **Mandarin (tradisional)** tetap tersedia.
Deteksi otomatis membandingkan OCR lokal pada maksimal lima halaman sampel sebelum
menerjemahkan. Bahasa yang ditemukan tampil pada daftar pekerjaan. Jika hasilnya
kurang yakin atau bahasa sampel berbeda, unggah ulang dengan pilihan manual.
Deteksi ini memerlukan ketiga model OCR terpasang; tidak memerlukan API key.
Jepang memakai manga-ocr; Mandarin memakai pengenal
EasyOCR khusus `ch_sim` atau `ch_tra`. Ketiganya diterjemahkan ke Indonesia oleh
NLLB lokal. Pemilihan bahasa disimpan bersama job dan digunakan kembali saat retry.
Detektor mengutamakan kana untuk Jepang dan membandingkan pembacaan Han untuk
Mandarin; karakter Han yang tidak cukup jelas akan menghasilkan permintaan pilihan
manual. Satu PDF menggunakan satu bahasa sumber.

Untuk memperbarui instalasi Jepang yang sudah ada, jalankan:

```powershell
docker compose build local-ai
docker compose --profile setup run --rm model-setup
docker compose up -d --build
```

Setup menambah dua model OCR Mandarin dan memakai ulang NLLB yang sudah terpasang.
Job lama tetap berbahasa Jepang. Model tersimpan lokal dan tidak memerlukan API key.

Status mesin tersedia di halaman **Bank terjemahan** (`/memory`). Jika model
belum siap, jalankan kembali perintah `model-setup`, lalu
`docker compose restart local-ai`. Setup yang terputus menyimpan unduhan parsial;
inferensi tidak mengunduh model dan tidak mengirim gambar atau teks ke API cloud.
Jangan hapus volume `local_ai_models` atau `postgres_data` jika ingin mempertahankan
model dan bank terjemahan. Restart dan rebuild biasa mempertahankan keduanya.

## Bank terjemahan lokal

Bank dimulai kosong. OCR membaca teks dalam bahasa sumber, lalu worker mencari teks lengkap
yang cocok setelah normalisasi Unicode dan spasi. Teks baru diterjemahkan oleh
model NLLB lokal dan disimpan sebagai draf; koreksi manual selalu diprioritaskan.
Bank ini tidak berisi seluruh kemungkinan kalimat Jepang atau Mandarin. Kalimat yang hanya
mirip ditampilkan sebagai saran untuk ditinjau, bukan dipakai otomatis, agar
perbedaan arti seperti negasi tidak tertukar.

Di `/memory`, kamu dapat mencari, menambah, mengoreksi, menghapus, mengimpor,
dan mengekspor pasangan Jepang/Mandarin-Indonesia. Setiap entri memiliki bahasa
sumber; pencocokan, koreksi, dan saran tidak bercampur antarbahasa. Filter bahasa
juga berlaku pada ekspor JSON. Istilah/frasa tetap dicocokkan
sebagai teks lengkap, bukan mengganti kata di tengah kalimat. Koreksi berlaku
pada terjemahan baru; halaman yang sudah menjadi checkpoint atau PDF hasil
tidak diubah. Unggah ulang PDF untuk menerapkan koreksi ke seluruh halaman.

Format impor adalah array JSON (maksimal 20 MB dari antarmuka):

```json
[
  {"source_language": "ja", "source_text": "\u3042\u308a\u304c\u3068\u3046", "translated_text": "Terima kasih", "category": "verified"},
  {"source_language": "zh-Hans", "source_text": "\u8c22\u8c22", "translated_text": "Terima kasih", "category": "verified"},
  {"source_language": "zh-Hant", "source_text": "\u8b1d\u8b1d", "translated_text": "Terima kasih", "category": "verified"}
]
```

Kategori manual adalah `verified` atau `glossary`. Ekspor menyertakan versi model
pada draf `machine` agar hasil model yang berbeda tidak digunakan kembali.

## Gaya dialog Indonesia

Hasil mesin untuk balon dialog diperhalus secara lokal ke gaya percakapan:
`Saya tidak mengerti. Apakah Anda sudah selesai?` menjadi
`Aku nggak ngerti. Apa kamu udah selesai?`. Aturan yang sama berlaku untuk
Jepang, Mandarin sederhana, dan Mandarin tradisional, termasuk draf mesin
yang diambil kembali dari bank. Judul, SFX, dan koreksi manual mempertahankan
teksnya; narasi/caption tetap memakai register yang jelas. Bank menyimpan hasil mentah agar gaya suatu dialog
tidak terbawa ke judul dengan teks sumber yang sama.

Penyuntingan ini memakai aturan frasa terbatas, tanpa API atau unduhan model
tambahan. Ini memperhalus pilihan kata; kesalahan OCR, makna, dan konteks dari
NLLB masih perlu ditinjau melalui Bank terjemahan.

PDF yang sudah selesai tetap tersedia. Unggah ulang PDF untuk menerapkan gaya
baru ke seluruh halaman. Saat pekerjaan lama dilanjutkan, checkpoint dengan
versi gaya berbeda diproses ulang agar hasilnya konsisten.
Impor mengikuti `source_language` setiap entri, bukan pilihan bahasa pada formulir.
File lama tanpa `source_language` tetap dianggap Jepang (`ja`).

## Alur terjemahan MVP

1. Login, pilih bahasa sumber, lalu upload satu PDF manga atau manhua.
2. Worker merender halaman hingga status `READY_FOR_TRANSLATION`.
3. Tekan **Mulai terjemahan** untuk menjalankan mesin lokal.
4. Worker membaca teks dengan OCR sesuai bahasa dan detektor CRAFT lokal, mencari teks
   di translation memory bahasa tersebut, menerjemahkan teks baru dengan NLLB ke Indonesia,
   menyimpan pasangan baru ke database, serta memvalidasi kotak teks dan
   area penempatan balon/panel. Worker menampilkan progres per
   halaman, menempatkan terjemahan Indonesia, dan menyusun PDF hasil. Halaman
   webtoon yang sangat panjang otomatis dibagi menjadi tile vertikal dengan
   overlap default 20%, lalu koordinatnya dipetakan kembali dan blok duplikat
   digabungkan. Tile yang sudah berhasil disimpan sebagai checkpoint sementara,
   sehingga retry melanjutkan dari tile yang gagal tanpa mengulang tile awal.
   Deteksi yang menyentuh batas internal tile dibuang agar teks terpotong tidak
   ikut dipasang ke hasil.
   Jika koordinat hasil pertama tidak aman untuk dirender, halaman tersebut
   dipindai ulang satu kali tanpa mengulang
   checkpoint halaman sebelumnya. Kegagalan akhir membedakan overlap area,
   teks yang tidak muat, dan masking teks sumber yang tidak aman.
   Worker memproses satu job pada satu waktu. HTTP 429, HTTP 5xx, timeout, dan
   gangguan koneksi dipindahkan
   ke status `TRANSLATION_RETRY_WAIT` agar worker dapat mengerjakan job lain.
   Retry tertunda memakai hint `Retry-After`, jitter, dan jadwal 1/5/15 menit
   untuk gangguan layanan atau 1/15/60 menit untuk rate limit. Dashboard
   menampilkan alasan serta waktu percobaan berikutnya dalam WIB.
   Setiap halaman selesai disimpan sebagai checkpoint selama 7 hari. Jika
   halaman 8 gagal, tombol **Coba terjemahkan lagi** melanjutkan dari halaman 8.
   Celery Beat memulihkan worker yang berhenti, mengantrekan retry jatuh tempo,
   dan membersihkan checkpoint kedaluwarsa setiap hari pukul 03.00 WIB. Setelah
   tiga retry tertunda gagal, pengguna masih dapat mencoba ulang secara manual.
5. Saat status `COMPLETED`, tekan **Download PDF**.
6. Job yang sudah siap, sedang menunggu retry, selesai, atau gagal dapat dihapus
   dari riwayat. Tindakan ini juga menghapus PDF asli, preview, checkpoint, dan
   PDF hasil dari storage.

Riwayat ditampilkan 10 job per halaman agar dashboard tetap ringan ketika jumlah
PDF bertambah.

File preview dan hasil tetap berada di `storage/` dan tidak dilacak Git. Model
lokal berada di volume Docker `local_ai_models`; translation memory berada di PostgreSQL.

Untuk mengembangkan frontend/backend di host, database dan Redis juga harus
dapat diakses lewat `localhost`. Sesuaikan `DATABASE_URL`, `REDIS_URL`,
`STORAGE_ROOT`, dan `LOCAL_AI_URL` di `backend/.env`. Service AI dapat dibuka
hanya ke host setelah model dipasang:

```powershell
docker compose run --rm --no-deps -p 127.0.0.1:8001:8001 local-ai
```

Gunakan `LOCAL_AI_URL=http://localhost:8001` pada backend di host. Untuk proses
PDF, jalankan worker Celery juga; alur lengkap paling mudah dijalankan melalui
Docker Compose.

```powershell
cd frontend
npm install
npm run dev
```

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\fastapi dev app/main.py
```

## Verifikasi

```powershell
cd frontend
npm run lint
npm run typecheck
npm test
npm run build
```

```powershell
cd backend
.\.venv\Scripts\python -m pytest
```

```powershell
docker compose run --rm --no-deps local-ai python -m pytest tests
```
