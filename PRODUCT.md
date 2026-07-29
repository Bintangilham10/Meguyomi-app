# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Pengguna utama adalah pembaca atau penerjemah manga berbahasa Indonesia yang memiliki PDF manga Jepang dan ingin menghasilkan PDF versi bahasa Indonesia dalam satu alur kerja privat.

## Product Purpose

Meguyomi menerima satu PDF manga Jepang, menyiapkan setiap halaman, menerjemahkan teks dengan AI, memasang hasil terjemahan kembali ke halaman, dan menyediakan PDF hasil untuk diunduh.

## Positioning

Meguyomi mempertahankan alur dan bentuk PDF asli. Proses per halaman dapat dipantau dan dilanjutkan dari checkpoint ketika layanan AI atau worker terganggu.

## Operating Context

Pengguna masuk ke workspace privat, mengunggah PDF, menunggu persiapan halaman, memulai terjemahan ketika siap memakai kuota Gemini, memantau progres, mencoba ulang pekerjaan yang dapat dipulihkan, lalu mengunduh hasil.

## Capabilities and Constraints

- Input MVP adalah PDF manga Jepang dengan batas 50 MB dan 100 halaman.
- Output adalah PDF dengan teks berbahasa Indonesia.
- Pemrosesan berjalan berurutan per halaman.
- Status, checkpoint, retry tertunda, dan hasil unduhan sudah menjadi bagian kontrak aplikasi.
- UI tidak boleh mengubah route, nama field formulir, atau kontrak API yang ada.

## Brand Commitments

Nama produk adalah Meguyomi. Bahasa utama antarmuka adalah bahasa Indonesia. Pengguna meminta identitas yang terasa dekat dengan manga, memakai karakter anime 2D orisinal, dan menghindari tampilan dashboard AI generik.

## Evidence on Hand

Implementasi frontend dan backend yang bekerja tersedia di repository. Tidak ada testimonial, pelanggan, metrik komersial, atau klaim performa yang boleh dibuat.

## Product Principles

- Tugas utama harus terlihat dan dapat dilakukan dengan cepat.
- Progres dan kegagalan harus mudah dipahami serta dapat dipulihkan.
- Materi manga pengguna diperlakukan sebagai dokumen privat.
- Kepribadian visual tidak boleh mengaburkan status pekerjaan.

## Accessibility & Inclusion

Kontrol harus dapat digunakan dengan keyboard, memiliki focus state yang jelas, menjaga kontras teks, dan menghormati preferensi reduced motion.
