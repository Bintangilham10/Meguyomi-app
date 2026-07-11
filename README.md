# Meguyomi

Meguyomi adalah proyek aplikasi web privat untuk menerjemahkan manga dalam
format PDF dari bahasa Jepang ke bahasa Indonesia. Alur MVP yang direncanakan
meliputi login, upload PDF, pemrosesan terjemahan di latar belakang, pratinjau,
dan download PDF hasil terjemahan.

Fondasi aplikasi sudah menyediakan Next.js, FastAPI, Celery, PostgreSQL, Redis,
dan Docker Compose. Fitur login, upload, serta integrasi AI belum dibuat.

## Struktur proyek

- `frontend/` — aplikasi web Next.js dan aset publik.
- `backend/app/api/` — endpoint HTTP FastAPI.
- `backend/app/core/` — konfigurasi dan utilitas inti backend.
- `backend/app/db/` — koneksi database dan migrasi.
- `backend/app/models/` — model database.
- `backend/app/schemas/` — schema request dan response.
- `backend/app/services/` — pipeline PDF, OCR, terjemahan, dan penyusunan hasil.
- `backend/app/tasks/` — job pemrosesan latar belakang.
- `backend/tests/` — pengujian backend.
- `docs/` — dokumentasi produk dan teknis.
- `storage/` — file upload dan hasil pemrosesan lokal; isinya tidak dilacak Git.

## Menjalankan aplikasi

1. Salin `.env.example` menjadi `.env`, lalu ganti password database lokal.
2. Jalankan seluruh layanan:

   ```powershell
   docker-compose up --build
   ```

3. Buka frontend di `http://localhost:3000` dan dokumentasi API di
   `http://localhost:8000/docs`.

Untuk pengembangan tanpa container, gunakan perintah berikut:

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
npm run build
```

```powershell
cd backend
.\.venv\Scripts\python -m pytest
```
