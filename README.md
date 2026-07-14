# Meguyomi

Meguyomi adalah proyek aplikasi web privat untuk menerjemahkan manga dalam
format PDF dari bahasa Jepang ke bahasa Indonesia. Alur MVP yang direncanakan
meliputi login, upload PDF, pemrosesan terjemahan di latar belakang, pratinjau,
dan download PDF hasil terjemahan.

Fondasi aplikasi sudah menyediakan Next.js, FastAPI, Celery, PostgreSQL, Redis,
Docker Compose, login privat satu akun, serta UI dan API upload/riwayat PDF.
Integrasi AI, pemrosesan terjemahan, pratinjau, dan download hasil belum dibuat.

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
2. Build image API untuk menyiapkan utilitas keamanan:

   ```powershell
   docker-compose build api
   ```

3. Buat hash Argon2 untuk password login dan salin hasilnya ke
   `ADMIN_PASSWORD_HASH`. Password dimasukkan melalui prompt dan tidak tampil di
   command history:

   ```powershell
   docker-compose run --rm api python -m app.core.password_cli
   ```

4. Buat session secret dan salin hasilnya ke `SESSION_SECRET`:

   ```powershell
   docker-compose run --rm api python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

5. Jalankan seluruh layanan:

   ```powershell
   docker-compose up --build
   ```

6. Buka frontend di `http://localhost:3000` dan dokumentasi API di
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
