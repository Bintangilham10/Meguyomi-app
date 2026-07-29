# Meguyomi Visual System

## Direction

Meguyomi memakai dunia visual meja kerja penerjemah manga: lembar proof, tinta editorial, tanda koreksi merah, dan screentone. Karakter penerjemah anime orisinal menjadi jangkar brand, sementara area kerja tetap cepat dipindai.

## Palette

- Paper: `#eef0ed`
- Surface: `#fafbf8`
- Ink: `#17181b`
- Muted ink: `#62656b`
- Coral: `#e74749`
- Coral dark: `#b9272d`
- Line: `#c9cbc6`
- Danger memakai coral dark agar halaman hanya memiliki satu keluarga aksen.

Warna dikunci pada mode terang karena konteks penggunaan menyerupai meja proof di ruang kerja dengan cahaya netral.

## Typography

- Display: Arial Black atau fallback sans-serif berat dan rapat.
- UI dan body: Arial, Helvetica, sans-serif.
- Angka memakai `font-variant-numeric: tabular-nums`.
- Heading tidak memakai gradient, serif dekoratif, atau uppercase tracking berulang.

## Composition

- Dashboard memakai komposisi asimetris: upload sebagai tugas utama, karakter sebagai jangkar visual, lalu riwayat pekerjaan selebar halaman.
- Login memakai split editorial dengan karakter yang sama.
- Mobile runtuh menjadi satu kolom, upload selalu muncul sebelum dekorasi.
- Halftone hanya dipakai pada bidang ilustrasi, bukan di belakang teks panjang.

## Components

- Radius panel 14px, kontrol 10px, dan chip status 8px.
- Tombol utama memakai coral solid dengan teks putih.
- Tombol sekunder memakai surface dengan garis ink.
- Panel hanya dipakai untuk kelompok tugas nyata. Baris job dipisahkan oleh ruang dan satu garis bawah.
- Status tidak memakai titik dekoratif. Label status sendiri membawa makna.

## Motion

Satu gerak karakter yang sangat lembut memberi kehidupan pada brand. Hover dan active state memberi feedback pada kontrol. Semua gerak dinonaktifkan saat `prefers-reduced-motion: reduce`.

## Imagery

`frontend/public/meguyomi-translator.png` adalah karakter anime orisinal yang dibuat untuk proyek ini. Gunakan sebagai visual utama pada dashboard dan login, dengan ukuran terreservasi untuk mencegah layout shift.
