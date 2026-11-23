# Konstitusi desain portal JAGAHUTAN

Dokumen ini mengikat semua iterasi UI di portal dan dashboard React nanti.
Tujuannya mencegah tiap halaman punya arah desain sendiri. Kalau sebuah usulan
melanggar aturan di sini, usulan itu yang ditolak, bukan aturannya.

## Karakter

Tenang, lapangan, editorial-teknis. Data yang ramai, bukan antarmukanya.
Satu hal boleh menonjol per layar, sisanya diam.

## Palet (terkunci)

| Peran | Token | Nilai |
|---|---|---|
| Latar | `--bg` | `#0a1712` |
| Permukaan | `--panel` | `#10241c` |
| Permukaan dalam | `--panel-2` | `#0d1f17` |
| Garis | `--line` | `#1f3a2e` |
| Garis halus | `--line-soft` | `#173026` |
| Teks | `--text` | `#eaf3ec` |
| Teks body | `--body` | `#c9dccf` |
| Label | `--label` | `#8fb5a0` |
| Garis edge | `--edge` | `#6f9080` |
| Aksen aksi | `--amber` | `#ff8a3d` |
| Bahaya | `--ember` | `#ff5a2b` |
| Peringatan | `--gold` | `#ffb02e` |
| Status aman | `--green` | `#4caf7a` |
| Angka pahlawan | `--warm` | `#ffd2ad` |
| Edge menuju Gold | `--edge-gold` | `#c08a52` |

Hijau gelap dan amber adalah identitas karhutla, bukan tema gelap default.
Jangan mengganti palet, menambah gradien, atau memakai ungu, krem, dan ungu-indigo.
Hex baru di luar tabel ini dilarang. Kalau butuh turunan warna, pakai token yang
ada atau `color-mix`, bukan nilai heksadesimal baru.

Aturan peran warna:

- Amber hanya untuk aksi utama, fokus, dan perhatian. Bukan dekorasi, bukan
  border semua kartu.
- Hijau hanya untuk status berhasil atau aman.
- Amber dan hijau tidak boleh menjadi satu-satunya pembeda makna.

## Tipografi

Tiga keluarga, tidak lebih:

| Peran | Keluarga | Dipakai untuk |
|---|---|---|
| Display | Fraunces | h1 dan judul seksi |
| UI | Inter | teks, tombol, label, tabel |
| Data | JetBrains Mono | nama tabel, angka, kode, id |

Skala target:

| Peran | Ukuran |
|---|---|
| Display hero | `clamp(2.5rem, 4vw, 3.5rem)` |
| Display halaman | `clamp(2rem, 5vw, 3rem)` |
| Angka pahlawan | `3.5rem` |
| Judul seksi | `1.35rem` |
| Subjudul | `1.1rem` |
| Body | `0.95rem` |
| Kecil | `0.85rem` |
| Label kapital | `0.72rem`, tracking `0.1em` |

Hanya satu ukuran label kapital. Jangan menambah ukuran baru untuk satu halaman.
Mono mengikuti ukuran konteksnya, tidak pernah di bawah `0.8rem` untuk isi.

Setiap `font-size` dan `border-radius` wajib berasal dari tabel di dokumen ini.
Nilai rem atau px mentah di luar skala ditolak dalam review, termasuk nilai yang
"hanya beda sedikit".

## Spasi dan bentuk

- Skala spasi: 4, 8, 12, 16, 20, 24, 32, 48, 64.
- Padding halaman: 4rem desktop, 1.5rem di bawah 1000px.
- Kepala halaman: 64px atas, 32px bawah. Jarak antar seksi: 20px.
- Radius: 16px kartu, 12px panel dalam, 8px kontrol, 999px pil.
- Elevasi hanya garis 1px. Bayangan hanya untuk lapisan mengambang seperti menu akun.
- Maksimal satu ilustrasi per halaman. Gradien hanya diizinkan untuk lanskap
  hero dan glow kanvas lineage, bukan untuk kartu, tombol, atau teks. Warna
  gradien lanskap dikecualikan dari aturan token.
- Bayangan hanya untuk lapisan mengambang dan kartu statistik di hero.
- Maksimal satu tingkat permukaan bersarang. Kartu di dalam kartu di dalam garis
  adalah tanda desain yang perlu disederhanakan.

## Kepadatan

- Perbandingan data memakai tabel, bukan kumpulan kartu.
- Grid kartu identik hanya boleh kalau itemnya benar-benar sejajar dan jumlahnya
  empat atau kurang.
- Angka dan identifier tidak dipotong. Kalau sempit, perkecil kolom lain.
- Baris tabel minimal 44px, sel 12 sampai 16px.
- Tautan di dalam tabel wajib punya penanda tetap, bukan hanya warna saat hover.

## Copy

- Bahasa Indonesia, faktual, tanpa hiperbola.
- Jangan mengubah angka, nama tabel, nama kolom, ambang, dan istilah kontrak.
  Editor visual tidak berwenang atas isi data.
- Tanpa emoji, tanpa em dash, tanpa elipsis dekoratif.
- Judul boleh memakai titik. Label kapital untuk kategori, bukan kalimat.

## Aksesibilitas

- Kontras teks minimal 4,5:1, grafik minimal 3:1.
- Fokus keyboard selalu terlihat, minimal 2px amber dengan offset.
- Target klik minimal 40px, termasuk chip dan tombol kecil.
- Ikon tanpa teks wajib punya nama aksesibel.
- Status tidak boleh hanya dibedakan warna.

## Gerak dan dependensi

- Transisi hanya warna dan border, 120 sampai 200ms.
- Tanpa bounce, scale, parallax, atau animasi hiasan.
- Tanpa pustaka atau font baru. Ikon memakai SVG inline.
- JavaScript vanilla maksimal 20 baris per perilaku.

## Proses iterasi

1. Audit menghasilkan inventaris temuan, bukan perubahan.
2. Tiap halaman maksimal enam perubahan per putaran.
3. Perubahan diterapkan, lalu dibandingkan lewat screenshot dan tes.
4. Satu putaran konsistensi lintas halaman menutup iterasi.
5. Iterasi berjalan di branch sendiri dan masuk lewat PR ke `dev`.
