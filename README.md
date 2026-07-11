# Meguyomi

Meguyomi adalah proyek aplikasi web privat untuk menerjemahkan manga dalam
format PDF dari bahasa Jepang ke bahasa Indonesia. Alur MVP yang direncanakan
meliputi login, upload PDF, pemrosesan terjemahan di latar belakang, pratinjau,
dan download PDF hasil terjemahan.

Repository ini baru berisi struktur awal monorepo. Next.js, FastAPI, worker,
database, Docker, dan integrasi AI belum di-scaffold.

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
