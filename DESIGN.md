# Meguyomi Visual System

Meguyomi memakai bahasa visual studio editorial untuk pembaca manga: tipografi display yang tebal, bidang charcoal hangat, aksen coral, aqua, dan lime, serta maskot Alya 3D sebagai teman baca.

## Direction

Halaman terasa seperti ruang kreatif kecil yang tenang, bukan dashboard SaaS. Upload menjadi tugas utama. Alya menjadi potret anime 3D Alya yang dibuat secara prosedural berdasarkan referensi pengguna yang bisa diputar dengan drag, disentuh pada kepala atau buku, memiliki reaksi berbeda, dan dapat dijeda tanpa mengganggu pekerjaan.

## Palette

- Charcoal background: `#0c1019`
- Surface: `#141b27`
- Text: `#f0f1f4`
- Muted: `#a1abbc`
- Coral action: `#ff7b72`
- Aqua signal: `#89dce0`
- Lime status: `#d4ef98`

## Typography

- Display: local `Space Grotesk` for headings and labels.
- Body: local `Manrope` for readable Indonesian UI copy.
- Fonts are bundled under `frontend/public/fonts`, so the interface does not depend on an external network at runtime.

## Motion

- Alya floats gently, shifts a small amount toward the pointer, and uses orbit controls for touch or mouse rotation.
- Orbit lines and the accent spark drift slowly.
- Head, book, and greeting controls trigger distinct Indonesian reactions.
- A visible pause button stops character motion.
- The pause preference persists across page navigation and reloads. It also updates across browser tabs.
- Character animations pause when the stage is outside the viewport or the browser tab is hidden; WebGL failure shows a reloadable fallback.
- `prefers-reduced-motion` disables animation and pointer parallax.

## Composition

- Top bar: brand, Studio/Bank navigation, account state.
- Hero: upload console on the left, Alya character stage on the right.
- Signal strip: real local-AI status, archive count, supported source languages.
- Queue: existing translation jobs keep their actions, progress, retry, preview, download, and delete behavior.
- Login and translation memory use the same chrome and visual system.

## Responsive behavior

Desktop uses a two-column hero and three-column signal strip. Below 800px the experience becomes one column, keeps the upload before decoration, stacks the character stage, and presents job controls below each job. The layout is checked at 320px, 390px, 768px, and 1440px.

On mobile login, the form comes before the character in both visual order and keyboard navigation. The introductory heading remains available to assistive technology.
