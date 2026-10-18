# Übergabe: Bessere 2.5x-Skalierung für DraStic auf dem Anbernic RG DS (ROCKNIX)

Stand: 2026-10-18. Ergebnis einer Claude-Code-Cloud-Sitzung. **Noch kein Code geschrieben, nichts gebaut, nichts auf dem Gerät getestet.** Alle Performance-Angaben sind Schätzungen.

## 1. Ziel

DraStic skaliert auf dem RG DS jeden DS-Bildschirm (256×192) im Vollbild auf 640×480 = **Faktor 2.5**. Aktuell passiert das bilinear (weich/verwaschen). Ziel: ein schneller, scharfer, flimmerfreier Skalierer.

## 2. Hardware & Software (recherchiert, ROCKNIX-Commit `57faded6`)

- RG DS: Rockchip **RK3568**, Mali-G52 2EE, 4× Cortex-A55. Zwei DSI-Panels à **640×480**, beide mit Goodix-Touch.
  DTS: `projects/ROCKNIX/devices/RK3566/linux/dts/rockchip/rk3568-anbernic-rg-ds.dts`. Gebaut als Teil der Gerätefamilie **RK3566**.
- Display-Stack: KMS/DRM → **Sway** (wlroots 0.19.3) → **SDL2** (`SDL_VIDEODRIVER=wayland`) → SDL-Renderer **opengles2** (libmali oder Panfrost).
- DraStic 2.5.2.2 aarch64 (closed source), heruntergeladen von `github.com/ROCKNIX/packages/raw/main/drastic.tar.gz`. Linkt nur `libSDL2`, nicht GLES direkt.

## 3. Wie DraStic in ROCKNIX eingebunden ist

Paket: `projects/ROCKNIX/packages/emulators/standalone/drastic-sa/`

| Datei | Zweck |
|---|---|
| `package.mk` | Baut den Hook: `${CC} ${CFLAGS} -shared -fPIC -o libdrastouch.so libdrastouch.c -ldl` |
| `sources/libdrastouch.c` | **ROCKNIX-eigener, quelloffener LD_PRELOAD-Hook** (~950 Zeilen): Touch, Fenstergröße, Mikrofon, **Shader** |
| `scripts/start_drastic.sh` | Setzt `LD_PRELOAD=/usr/lib/libdrastouch.so`, `DSHOOK_SHADER="${SHADER:-none}"`, schreibt `hires_3d` per `sed` in die drastic.cfg |
| `config/RK3566/drastic.cfg` | `screen_orientation = 1`, `hires_3d = 0`, `threaded_3d = 1` |
| `projects/ROCKNIX/packages/ui/emulationstation/config/common/es_features.cfg` (~Z. 1965) | Shader-Auswahl im ES-Menü (`<feature name="shader">`) |
| `projects/ROCKNIX/packages/wayland/compositor/sway/autostart/111-sway-init` (~Z. 166/233) | Zweiter Bildschirm, `for_window [app_id="drastic"] …` |

**Video-Pfad:** DraStic lädt jeden DS-Screen als Streaming-Textur (256×192, bei Hi-Res-3D 512×384) und zeichnet ihn per `SDL_RenderCopy`. Der Hook überschreibt u. a. `SDL_CreateTexture` (markiert DS-Screen-Texturen), `SDL_RenderCopy`, `SDL_CreateWindow`/`SDL_SetWindowSize` (ein Fenster über beide Displays), `SDL_PollEvent` (Touch).
Ist `DSHOOK_SHADER` gesetzt, ersetzt `run_shader_copy()` (Z. ~441) den Copy für DS-Screens durch **einen GLES2-Pass**.

**Vorhandene Shader im Hook** (Konstanten `SHADER_*` Z. ~66, Zuordnung `getenv("DSHOOK_SHADER")` Z. ~885):
`none` (bilinear, Default), `sharp-bilinear` (Prescale min. 2 → bei 2.5x ~10 % Kanten-Unschärfe), `sharp-shimmerless`, `quilez`, `scanlines`, `lcd3x`, `lcd1x-nds-color`.

**Shader-Konventionen im Hook** (für neue Shader übernehmen):
- Varying `v_texcoord`; Uniforms `u_texture`, `u_texture_size` (Quelle), `u_output_size` (Ziel in physischen Pixeln).
- Makro `SWIZ(...)` um jeden `texture2D`-Aufruf (BGRA-Swizzle auf GLES).
- Bestehende Shader nutzen `precision mediump float` → für unseren Shader **highp** verwenden (mediump = fp16 auf Mali, zu ungenau bei 256–512 Texeln).
- Nur ein Pass; Mehrpass bräuchte ein eigenes FBO.

**Nicht genutzt von Standard-ROCKNIX:** Steward-Fus Hook und trngajes `advanced_drastic` (Drittanbieter, `libdrastic` nur binär → dort nicht änderbar).
Notfall-Alternative: Detour per Adresse in DraStic 2.5.2.2 (`update_screen` 0x8a120, `update_screens` 0x8a690, `screen_copy16` 0x88290, vgl. github.com/steward-fu/nds `detour/hook.c`) – nicht nötig.

**Unverifiziert:** genaue Output-Positionen der beiden Displays in Sway (automatische Platzierung?), welcher DSI-Connector physisch oben ist.

## 4. Der Algorithmus: 2→5-Coverage-Kernel („area“)

Ein Ausgabepixel ist 0,4 Quellpixel breit. Pro Periode (2 Quellpixel p0,p1 → 5 Ausgabepixel), je Achse:

| Phase k | Quellbereich | Gewicht p0 | Gewicht p1 |
|---|---|---|---|
| 0 | 0.0–0.4 | 1 | 0 |
| 1 | 0.4–0.8 | 1 | 0 |
| 2 | 0.8–1.2 | ½ | ½ |
| 3 | 1.2–1.6 | 0 | 1 |
| 4 | 1.6–2.0 | 0 | 1 |

→ Muster `p0, p0, avg(p0,p1), p1, p1`. In 2D: 2×2-Block → 5×5-Block = 16 Kopien, 8 Zweier-Mittel, 1 Vierer-Mittel. **Keine Multiplikationen**, nur Halbierungs-Adds.

Eigenschaften:
- Jedes Quellpixel deckt immer genau 2,5 Ausgabepixel ab → **kein Breitenflimmern** beim Scrollen (Nearest: 2/3 px abwechselnd).
- Nur jedes 5. Pixel ist gemischt, exakt 50/50 → scharf.
- Mathematisch identisch mit sharp-bilinear bei Prescale 3 (bestehender Shader nutzt Prescale 2 → 10 % Bleed).
- **Offene Frage:** Wie stark unterscheidet sich das vom vorhandenen `sharp-shimmerless`? Muss am Gerät bzw. per PC-Simulation verglichen werden – evtl. ist der Gewinn von „area“ klein und der eigentliche Mehrwert ist „area-sharp“.

**Hi-Res-3D (512×384 → 640×480, Faktor 1.25):** Periode 4 → 5:
`p0 | ¼p0+¾p1 | ½p1+½p2 | ¾p2+¼p3 | p3` (alles Vielfache von ¼).
DraStic verdoppelt die 2D-Ebenen per Nearest auf 512 → 2D sieht in beiden Modi identisch aus, 3D behält Details.

### GLES2-Fragment-Shader „area“ (ein bilinearer Fetch, exakt für 2.5x und 1.25x)

Textur muss `GL_LINEAR` + `CLAMP_TO_EDGE` sein. An die Hook-Konventionen angepasst:

```glsl
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
varying vec2 v_texcoord;
uniform sampler2D u_texture;
uniform vec2 u_texture_size;   // 256x192 oder 512x384
uniform vec2 u_output_size;    // 640x480
void main() {
    vec2 scale = u_output_size / u_texture_size;      // 2.5 bzw. 1.25
    vec2 p = v_texcoord * u_texture_size;             // Fragmentmitte in Quellpixeln
    vec2 i = floor(p + 0.5);                          // nächste Texelgrenze
    vec2 w = clamp((p - i) * scale + 0.5, 0.0, 1.0);  // Abdeckung des hinteren Texels
    gl_FragColor = SWIZ(texture2D(u_texture, (i - 0.5 + w) / u_texture_size));
}
```

Handgeprüft bei 2.5x: Fragmentmitten bei p = 0.2, 0.6, 1.0, 1.4, 1.8 → w = 1, 0, ½, 1, 0 → p0, p0, ½/½, p1, p1. ✓
Bei 1.25x: 1, ¼/¾, ½/½, ¾/¼, 1. ✓ p+0.5 liegt nie näher als 0,1 an einer Ganzzahl → robust gegen Float-Fehler.
Funktioniert auch allgemein (Coverage-AA), falls `u_output_size` mal nicht exakt passt.

### Variante „area-sharp“ (EPX-artige Regel, nur im Mischpixel)

Für das Paar p0|p1 mit Nachbarn l = p₋₁, r = p₂:

```
if (p0 != p1 && l == p0 && p1 != r) mid = p1;   // p1 ist 1-px-Struktur → bekommt 3 px
else if (p0 != p1 && r == p1 && p0 != l) mid = p0;
else mid = avg(p0, p1);
```

- 1-px-Linien (DS-Schriften!) werden gleichmäßig 3 px breit statt halb verwaschen.
- Dithering und 3D (Nachbarn selten exakt gleich) fallen automatisch auf 50/50 zurück.
- Erst horizontal, dann vertikal auf den expandierten Zeilen anwenden.

GPU-Version (Agentenvorschlag): zwei Pässe – horizontal in ein 640×192-FBO, dann vertikal; Textur `GL_NEAREST`, Mischung im Shader:

```glsl
uniform sampler2D tex; uniform vec2 texSize; uniform float scale; varying vec2 vTex;
bool eq(vec4 a, vec4 b){ vec3 d=abs(a.rgb-b.rgb); return max(d.r,max(d.g,d.b)) < 0.01; }
vec4 T(float x){ return texture2D(tex, vec2(x/texSize.x, vTex.y)); }
void main(){
  float p=vTex.x*texSize.x, i=floor(p+0.5), w=clamp((p-i)*scale+0.5,0.0,1.0);
  vec4 a=T(i-0.5), b=T(i+0.5);
  if (w>0.0 && w<1.0 && !eq(a,b)) {
    vec4 l=T(i-1.5), r=T(i+1.5);
    if (eq(l,a) && !eq(b,r)) w=1.0; else if (eq(b,r) && !eq(l,a)) w=0.0;
  }
  gl_FragColor = mix(a,b,w);
}
```

**Offen:** Der Hook kann bisher nur einen Pass. Entweder FBO-Unterstützung in `run_shader_copy()` ergänzen oder eine **Einpass-Variante** entwickeln (je Fragment bis zu 4×4 Nearest-Fetches um den 2×2-Block, Regel getrennt pro Achse; bei Mali-G52 und 2×307k Pixeln vermutlich unkritisch – messen).

### CPU-Referenz in C (für PC-Simulator / NEON-Fallback)

RGB565 → XRGB8888, ein Screen 256×192 → 640×480, `sharp` schaltet die Regel ein:

```c
#include <stdint.h>
static inline uint32_t c565(uint16_t c){
  uint32_t r=c>>11, g=(c>>5)&63, b=c&31;
  r=(r<<3)|(r>>2); g=(g<<2)|(g>>4); b=(b<<3)|(b>>2);
  return 0xFF000000u|(r<<16)|(g<<8)|b;
}
static inline uint32_t avg2(uint32_t a,uint32_t b){        /* bytewise, aufrundend (= vrhadd) */
  return (a|b) - (((a^b)>>1) & 0x7F7F7F7Fu);
}
static inline uint32_t pick(uint32_t l,uint32_t a,uint32_t b,uint32_t r,int sharp){
  if (sharp && a!=b) {
    if (l==a && b!=r) return b;
    if (r==b && a!=l) return a;
  }
  return avg2(a,b);
}
static void hrow(const uint16_t *s, uint32_t *d, int sharp){ /* 256 -> 640 */
  for (int x=0; x<256; x+=2, d+=5){
    uint32_t L=c565(s[x?x-1:0]), A=c565(s[x]), B=c565(s[x+1]),
             R=c565(s[x+2<256?x+2:255]);
    d[0]=d[1]=A; d[2]=pick(L,A,B,R,sharp); d[3]=d[4]=B;
  }
}
void ds_scale_2p5(const uint16_t *src,int sp,uint32_t *dst,int dp,int sharp){
  static uint32_t buf[4][640];
  uint32_t *U=buf[0],*A=buf[1],*B=buf[2],*D=buf[3],*t;
  hrow(src,A,sharp); for(int x=0;x<640;x++) U[x]=A[x];          /* oberer Rand */
  for (int j=0;j<96;j++){
    int yb=2*j+1, yd=(2*j+2<192)?2*j+2:191;
    hrow(src+yb*sp,B,sharp); hrow(src+yd*sp,D,sharp);
    uint32_t *o=dst+5*j*dp;
    for (int x=0;x<640;x++){
      o[x]=o[dp+x]=A[x];
      o[2*dp+x]=pick(U[x],A[x],B[x],D[x],sharp);
      o[3*dp+x]=o[4*dp+x]=B[x];
    }
    t=U; U=B; B=t;  t=A; A=D; D=t;   /* nächstes A = dieses D, nächstes U = dieses B */
  }
}
```

(Code handgeprüft inkl. Randbehandlung, aber nicht kompiliert.)

**NEON-Skizze (nur falls GPU-Weg scheitert):** `vld2q_u16` trennt gerade/ungerade Pixel; Nachbarn per `vextq_u16`; Mitte `vrhadd_u8` pro Farbebene, Regel per `vceqq`/`vbsl`; 5-fach-Expansion per `vqtbl2_u8` mit festen Indexvektoren, Ausgabe `vst4_u8`. Vertikal: Zeilen A/B je zweimal speichern, Mittelzeile `vrhaddq_u8`. Schätzung ~0,9 ms/Frame für beide Screens ≈ 5 % eines A55-Kerns. **Empfehlung: GPU-Shader, da der Pfad im Hook schon existiert.**

### Bewertung anderer Verfahren (Kurzfassung)

| Verfahren | Urteil bei 2.5x |
|---|---|
| Nearest | scharf, aber 2/3-px-Breitenwechsel, Flimmern beim Scrollen |
| Bilinear (aktueller Default) | überall weich |
| sharp-bilinear 2x (vorhanden) | gut, 10 % Kantenbleed |
| **area / 2→5** | scharf, flimmerfrei, praktisch kostenlos → **Default** |
| **area-sharp** | beste Lesbarkeit kleiner Schriften → **Option** |
| Bicubic/Lanczos | Ringing/Halos um 1-px-Text, teurer |
| xBR/ScaleFX/MMPX | erfindet Formen, flackert an bewegten 3D-Kanten; nicht als Default |
| Scale2x → 1.25 area | glättet 2D-Diagonalen, verformt Glyphen → evtl. Option „smooth 2D“ |

DS-Besonderheit: 2D und 3D kommen bereits zusammengesetzt an, lassen sich also nicht getrennt filtern.

## 5. Umsetzungsplan

1. ROCKNIX-Repo forken, Branch anlegen.
2. In `libdrastouch.c`: `SHADER_AREA` (+ später `SHADER_AREA_SHARP`) definieren, Fragment-Shader-String im Stil der vorhandenen, `switch` in der Shader-Init (Z. ~420) und `getenv`-Zuordnung (Z. ~885) erweitern (`"area"`, `"area-sharp"`).
3. Sicherstellen, dass die Quelltextur bei diesem Modus `GL_LINEAR` gefiltert ist (prüfen, was `run_shader_copy()` aktuell setzt).
4. `es_features.cfg`: Choices `area` / `area-sharp` beim DraStic-Feature `shader` ergänzen.
5. PC-Simulator: kleines Programm (C-Referenz oben bzw. Python), das Screenshots durch nearest / bilinear / sharp-bilinear / sharp-shimmerless / area / area-sharp schickt → Vergleichsbilder.
6. Cross-Compile der `.so` (aarch64), Test am Gerät, dann PR an ROCKNIX.

## 6. Entwicklungs- und Test-Workflow (ohne Image-Neubau)

- Cross-Compile, z. B. in WSL 2 / Ubuntu:
  `sudo apt install gcc-aarch64-linux-gnu`
  `aarch64-linux-gnu-gcc -O2 -shared -fPIC -o libdrastouch.so libdrastouch.c -ldl`
  (ggf. SDL2-/GLES-Header nötig – siehe `#include`s in der Datei; Abhängigkeit beim Linken nur `-ldl`.)
- Am RG DS: SSH in den ROCKNIX-Einstellungen aktivieren. Datei nach `/storage/` kopieren (`scp`).
- `/usr` ist schreibgeschützt (squashfs) → temporär überlagern:
  `mount --bind /storage/libdrastouch.so /usr/lib/libdrastouch.so`
  Neustart macht alles rückgängig.
- Shader wählen: im ES-Menü (wenn eingetragen) oder Startskript-Logik beachten: `DSHOOK_SHADER` kommt aus der ES-Einstellung `shader`.
- Screenshots: `grim` (Wayland) für Vorher/Nachher.

## 7. Status beim Nutzer

- RG DS läuft noch mit **alter ROCKNIX-Firmware**. Shader-Support im Hook gibt es erst seit 2026-06-19 → **mindestens Release 20260701 nötig**, aktuell ist **20261001**. Update geplant (OTA über WLAN, oder `.tar` für RK3566 nach `/storage/.update/` bzw. Freigabe `\\<IP>\update`, oder Neu-Flash mit `.img.gz`).
- Saves gesichert/zu sichern: `.dsv` in `roms/nds` (ROCKNIX leitet DraStics Backup-Ordner dorthin um), Savestates in `roms/savestates/nds`.
- Testspiele vorhanden: Pokémon Schwarz 2, Pokémon Platin, Final Fantasy IV, Mario Kart DS (gut für Schrift-, 2D- und 3D-Tests).
- Kartenleser vorhanden.

## 8. Offene Fragen / nächste Schritte

1. ROCKNIX-Version nach Update notieren (`Info`-Menü).
2. Vom Gerät holen: `/storage/.config/drastic/config/drastic.cfg`, `swaymsg -t get_outputs`, verwendeter GPU-Treiber (libmali/Panfrost).
3. Screenshots mit kleiner Schrift + 3D für PC-Vergleich.
4. Prüfen: Filtermodus der Quelltextur in `run_shader_copy()`, tatsächliches `u_output_size` (640×480?), Rolle von `hires_3d`.
5. Vergleich `area` vs. vorhandenes `sharp-shimmerless`.
6. Einpass- vs. Zweipass-Variante für `area-sharp`.

---

## 9. Stand nach Sitzung 2 (2026-10-18, lokal in WSL)

**Repo:** `./distribution` war unvollständig ausgecheckt (≈5 900 Dateien fehlten, Index zeigte alles als gelöscht) → per `git reset` + `git checkout -- .` aus HEAD `57faded` wiederhergestellt. Arbeitsbranch **`drastic-area-shader`**, Commit `d1f9a9f` (nur lokal, nicht gepusht).

**Wichtigste Erkenntnis (offene Frage 5 geklärt):** Der vorhandene `sharp-shimmerless` ist **mathematisch exakt der „area“-Filter** – bei 2,5x und 1,25x identische Samplepositionen (mit Brüchen nachgerechnet; im Simulator mit highp bitgenau gleich der CPU-Referenz). Ein eigener `area`-Eintrag wäre redundant → **nicht eingebaut**. Einziger Mangel von shimmerless: `precision mediump` (fp16 auf Mali) → im Simulator (Mesa senkt mediump ab) bis 9/255 Übersprechen bei 7,4 % der Pixel. → shimmerless jetzt mit highp.

**Änderungen im Commit:**
- `libdrastouch.c`:
  - neuer Shader `FRAG_AREA_SHARP` / `SHADER_AREA_SHARP` (7) / `DSHOOK_SHADER=area-sharp`, **Einpass**: pro Achse 1 Fetch (reiner Pixel), 2 (gemischt) bzw. 4 (gemischt + Regel nötig); schlimmstenfalls 16 Fetches im Zentrumspixel eines 5×5-Blocks. Regel nur bei Skalierung ≥ 2 je Achse → bei Hi-Res 3D (1,25x) = reines area.
  - Gleichheit **exakt** (Toleranz 0.0015 nur gegen Float-Fehler). Die ursprüngliche 0.01 war zu grob: gemischte Werte, die sich um 2/255 unterscheiden, galten als gleich → falsche Entscheidungen an 3D-Kanten.
  - Rundung der Gewichte nahe 0/1 (`w` liegt bei Phase 0/4 genau auf der Clamp-Grenze; ohne Snap würde Float-Rauschen die Regel auslösen).
  - `run_shader_copy()`: neuer `shader_tex_filter` – area-sharp erzwingt `GL_NEAREST` während des Passes, **sichert und restauriert** MIN/MAG-Filter (`glGetTexParameteriv` ergänzt). Vorher setzte der Hook gar keinen Filter (offene Frage 4: Textur kommt mit SDLs Filter, bei DraStic bilinear).
  - `FRAG_SHARP_SHIMMERLESS` → `#ifdef GL_ES` highp-Block (Desktop-GL-Pfad bleibt kompatibel).
- `es_features.cfg`: Choice `area-sharp` nach `sharp-shimmerless`.

**Verifiziert (PC):** kompiliert für x86_64 + aarch64 ohne neue Warnungen (SDL2-2.30.9-Header); Shader kompilieren als GLSL ES 1.00 und GLSL 1.20; `sim/run.sh` → alle Checks grün (GPU = CPU-Referenz ±1, Desktop-GL = GLES2, Hi-Res-Doppelung = 256er-Ergebnis). Benötigt glibc ≥ 2.38, ROCKNIX hat 2.44.

**Nicht verifiziert:** alles am Gerät (Mali-G52, Performance, Optik in echten Spielen).

**Beobachteter Zielkonflikt area-sharp:** 3D-Silhouetten vor **einfarbigem** Hintergrund werden nearest-artig gestuft (Hintergrund ist „exakt gleich“ → Regel greift). Bei Bewegung evtl. leichtes Kantenflimmern. Am Gerät mit Mario Kart DS prüfen; falls störend: Regel nur anwenden, wenn auch die *andere* Seite eine Konstante ist, oder Option nur für 2D-lastige Spiele empfehlen.

### PC-Simulator `rgds/sim/` (im Fork)
- `run.sh [eigenes.ppm]` – extrahiert die Shader-Strings direkt aus `libdrastouch.c`, rendert per EGL-surfaceless/llvmpipe (`gles_sim`, gleiche Quad/UV-Logik wie `run_shader_copy()`), vergleicht mit `ref.c` (CPU-Referenz, Festkomma), schreibt `out/*.png` und Vergleichsbögen `out/sheet-{text,lines,sphere,sprite}.png`.
- Eigene Screenshots: 256×192 als binäres PPM (P6) übergeben (z. B. `grim`-Screenshot zuschneiden, mit beliebigem Tool nach PPM).
- `fp16_check.py` – zeigt, warum highp nötig ist.

### Gerätetest (nächster Schritt)
1. ROCKNIX ≥ 20260701 (Shader-Support) installieren.
2. `libdrastouch.so` (aarch64, liegt in `~/projekte/drastic-rgds/`; neu bauen siehe Abschnitt 6) per `scp` nach `/storage/`, dann
   `mount --bind /storage/libdrastouch.so /usr/lib/libdrastouch.so`
3. Da `area-sharp` im ES-Menü der Firmware noch fehlt, per SSH in die ES-Konfiguration eintragen (Format laut `get_setting` in `profile.d/001-functions`): `nds.shader=area-sharp` für alle NDS-Spiele bzw. `nds["<rom-dateiname>"].shader=area-sharp` pro Spiel. Datei = `/storage/.config/system/configs/system.cfg`. Zum Vergleich einfach den Wert auf `sharp-shimmerless` ändern.
4. `/storage/.config/drastic/` → stderr-Log auf `[drastouch] shader_program=` ≠ 0 prüfen.
5. Vergleich `sharp-shimmerless` (jetzt highp) vs. `area-sharp` vs. bilinear mit `grim`-Screenshots; FPS mit DraStic-Framecounter (`show_frame_counter = 1`).
6. Danach PR an ROCKNIX (AGENTS.md verlangt `.img.gz`/`.tar`-Artefakte für betroffene Geräte im PR).

---

## 10. DS-only-Image „miniNIX“ (Branch `rgds-ds-only`, Fork github.com/LennartSchlass/miniNIX)

Remotes: `origin` = Fork (SSH), `upstream` = ROCKNIX/distribution. `drastic-area-shader` bleibt PR-Kandidat (nur Shader).

| Commit | Inhalt |
|---|---|
| RK3566: DS-only build | `DS_ONLY=yes`, `ENABLE_32BIT=no`, `DEBUG_PACKAGES=no` in `devices/RK3566/options`; Image-Plan 693 → 427 Pakete; es_systems = nds, tools, imageviewer |
| emulationstation | `patches/RK3566/ds-only-menu.patch` (`#ifndef ROCKNIX_DS_ONLY`): ohne Scraper, Updates (+ Update-Hinweis), RetroAchievements, Collections, Netplay, Moonlight, Cloud, RetroArch/PortMaster; `050-es_settings`: Start in NDS-Liste, Rest versteckt |
| nds-icons | Banner-Icon + Titel aus .nds/.zip/.7z → `images/<rom>-image.png` (128 px) + gamelist.xml, beim Boot vor ES |
| RG DS Komfort | Defaults `nds.shader=area-sharp`, `nds.threaded_3d=1`, `nds.bootlastgame=0` (Boot ins letzte Spiel abschaltbar, Default aus); Deckel (logind-Holdoff 5 s, Fake-Suspend kennt `gpio-keys-hall`); unterer Screen nach DraStic aus; Boot ins letzte Spiel über ES-„startup game“, einmal pro Boot, nur nach ≥ 15 s Spielzeit |

Build: `make docker-RK3566` (braucht Docker-Desktop-WSL-Integration). Ergebnis in `release/`. Achtung: Build überschreibt `documentation/PER_DEVICE_DOCUMENTATION/RK3566/SUPPORTED_EMULATORS_AND_CORES.md` – nicht committen.

Hinweis: Defaults in `system.cfg` greifen nur bei frischem `/storage` (Neu-Flash), nicht beim Update einer bestehenden Installation.

### Test-Checkliste am Gerät
- [ ] ES startet direkt in der NDS-Liste; keine anderen Systeme/Sammlungen; Menü ohne Scraper/Updates.
- [ ] Spiele zeigen DS-Icons + Titel (`.nds`, `.zip`, `.7z`); erster Boot mit vielen gepackten ROMs evtl. langsamer.
- [ ] Shader `area-sharp` aktiv (Spiel → erweiterte Optionen); Vergleich mit `sharp-shimmerless`; FPS.
- [ ] Deckel zu → Standby (auch < 30 s nach Boot/Aufwachen), Deckel auf → weiter; DraStic läuft nach Resume weiter.
- [ ] `udevadm info` am Hall-Gerät: `ID_INPUT_SWITCH=1`, TAGS enthält `power-switch`.
- [ ] Mit `system.suspendmode=off`: Fake-Suspend per Deckel.
- [ ] Nach Beenden von DraStic ist der untere Screen aus; Touch-Tastatur in ES geht noch.
- [ ] Boot ins letzte Spiel: beide Screens + Touch ok; nach Beenden erscheint ES; Spiel < 15 s beendet/Absturz → kein Auto-Start beim nächsten Boot; gelöschte ROM wird übersprungen. Abschalten: `nds.bootlastgame=0` in `/storage/.config/system/configs/system.cfg`.
- [ ] WLAN, SSH, Samba funktionieren.

### Gerätetest 2026-10-18 (Specific-Image, Build `cc1525d`)
- Bootet mit dem Specific-Image (Generic bleibt schwarz: RG353-u-boot kennt das RG DS nicht).
- Grundfunktion ok laut Nutzer.
- Hi-Res 3D läuft nicht flüssig → bleibt aus (Default). area-sharp wirkt ohnehin nur bei 256×192 (2,5x).
- Icons: funktionieren mit echten ROMs (Pokémon SW2/Platin, FF IV, Mario Kart); entstehen nur beim Boot → nach ROM-Kopie neu starten.
- Touch: per `evtest` gemessen – `fe5c0000` (event2) = oberes Panel, `fe5e0000` (event3) = unteres, beide nicht gedreht. Die ROCKNIX-Kalibrierung (`touchcontrol`) ist korrekt; ein Tausch (4eb35ff) war falsch und ist revertiert (0202985). Diagnose-Hook mit Touch-Log: siehe Sitzung, `touch_dbg()` in einer Kopie von libdrastouch.c.
- Boot ins letzte Spiel als befremdlich empfunden → Default `nds.bootlastgame=0`.

### nitro-sharp (Nachfolger von area-sharp)
Nutzer bemerkte kleine Kerben im Text (z. B. oben im T): Am Ansatz eines Stamms ist der Querbalken senkrecht nicht mehr „1 px dünn“, die Regel blieb unentschieden → halbtransparenter Pixel. `nitro-sharp` übernimmt in genau diesem Fall die Entscheidung der parallelen Nachbarkante (Nachbarzeilen bzw. -spalten im Quellbild); nur bei Einigkeit. Simulator: GPU = CPU-Referenz (±1), ~20 % weniger Mischpixel im Testtext, Kerben an Abzweigungen weg (`docs/nitro-sharp-vs-area-sharp.png`). `area-sharp` bleibt als Alias im Hook. Name: „Nitro“ = DS-Codename (NTR).

### nitro-sharp v4: Zwei-Pass-Aufbau (2026-10-18, nach Performance-Beschwerde)
**Befund:** v2/v3 (Einpass) waren auf dem Mali-G52 in 3D-/Dither-Szenen zu langsam. Ursachen:
1. Einpass muss pro Mischzeile die horizontale Mischung von **vier** Quellzeilen berechnen (bis 16 abhängige Fetches, tief verzweigt); mit 8er-Warps zahlt fast jede Gruppe den teuersten Pfad.
2. v3-Bedingung für die Nachbar-Abfrage (`la == br && …`) griff in 3D (keine zwei gleichen Farben) auf **jedem** Mischpixel → nochmals 16 Fetches.

**Lösung:** separabel. Pass 1: Quelle → Zwischentextur (Ausgabebreite × Quellzeilen, RGBA8, NEAREST, FBO), horizontale Regel inkl. Kreuzungs-Konsens über die Nachbar**zeilen**. Pass 2: Zwischentextur → Bildschirm, vertikale Regel, Konsens über die Nachbar**spalten** (reine Spalten per `pure_col(c) = ceil(c·s)`, benötigt `u_source_size`). Konsens nur bei „beide Seiten breit“ (`la && br`), alles andere mischt 50/50 (sicher gegen Dither-Flimmern).
Kosten pro Bildschirm (geschätzt): Pass 1 ≈ 123k px × 4 Fetches, Pass 2 ≈ 307k × ~2,7 → ≈ 1,3 M Texel statt ≈ 2,7 M (area-sharp) bzw. ≈ 4,6 M (v3 in 3D); flache Abhängigkeitsketten, zwei Zwischentexturen (Ping-Pong für beide Screens).
Hook: `alloc_pass_targets()`, Probe 64×64 bei Init (Fallback sharp-shimmerless), FBO-/Textur-Binding gesichert, Filter der DS-Textur vor Pass 2 restauriert, Destruktor nur mit GL-Kontext. **SWIZ nur in Pass 1** (Zwischentextur ist bereits in Ausgabereihenfolge; Doppel-Swizzle war der erste Fehler im PC-Test).
Erkenntnis SDL: Der GLES2-Renderer lädt ARGB8888 byteweise als `GL_RGBA` und swizzelt im eigenen Shader (`SDL_render_gles2.c`, `GLES2_IMAGESOURCE_TEXTURE_ARGB`) – das `.bgra` des Hooks ist daher treiberunabhängig korrekt, solange DraStic ARGB8888 nutzt.

**Verifikation PC:** `rgds/sim/run.sh` (GPU = zweistufige CPU-Referenz ±1, GLES2 = Desktop-GL, Hi-Res ±2 wegen Doppelrundung) und neu `rgds/sim/hooktest.sh`: baut SDL2 2.30.9 (offscreen+GLES2) lokal, lädt `libGLESv2` aus dem Ubuntu-Paket, führt `libdrastouch.so` per `LD_PRELOAD` in einem DraStic-ähnlichen Programm (`hooktest.c`, zwei 256×192-Streaming-Texturen, mehrere Frames) aus und vergleicht die Fensterpixel mit dem Simulator → **bitgenau** für nitro-sharp und sharp-shimmerless (640×480 und 384×288).
