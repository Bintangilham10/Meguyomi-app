# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Pengguna utama adalah pembaca atau penerjemah manga berbahasa Indonesia yang memiliki PDF manga dalam berbagai bahasa dan ingin menghasilkan PDF versi bahasa Indonesia dalam satu alur kerja privat.

## Product Purpose

Meguyomi menerima satu PDF manga dalam bahasa apa pun, menyiapkan setiap halaman, mendeteksi bahasa sumber per blok teks, menerjemahkannya ke bahasa Indonesia dengan AI, memasang hasil terjemahan kembali ke halaman, dan menyediakan PDF hasil untuk diunduh.

## Positioning

Meguyomi mempertahankan alur dan bentuk PDF asli. Proses per halaman dapat dipantau dan dilanjutkan dari checkpoint ketika layanan AI atau worker terganggu.

## Operating Context

Pengguna masuk ke workspace privat, mengunggah PDF, menunggu persiapan halaman, memulai terjemahan ketika siap memakai kuota Gemini, memantau progres, menghentikan atau melanjutkan pekerjaan dari checkpoint, lalu mengunduh atau mencetak PDF penuh maupun parsial.

## Capabilities and Constraints

- Input MVP adalah PDF manga dalam bahasa apa pun dengan batas 50 MB dan 100 halaman.
- Bahasa sumber dideteksi otomatis per blok sehingga satu halaman dapat memuat beberapa bahasa.
- Halaman webtoon yang sangat panjang dipindai sebagai tile vertikal overlap lalu koordinatnya digabungkan kembali.
- Output adalah PDF dengan teks berbahasa Indonesia.
- Hasil dengan koordinat bertabrakan atau kegagalan pembersihan teks yang terlalu tinggi tidak diterbitkan dan dapat dipindai ulang.
- Pemrosesan berjalan berurutan per halaman.
- Terjemahan aktif dapat dihentikan secara aman pada checkpoint terakhir; halaman yang sudah selesai tersedia sebagai PDF parsial untuk diunduh atau dicetak, dan proses dapat dilanjutkan.
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
