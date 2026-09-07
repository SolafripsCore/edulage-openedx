# tutor-contrib-edulage-theme

Tutor plugin that makes Open edX look like [edulage.org](https://edulage.org). It is the Open edX
side of the EduLage design system: the tokens, fonts, logos, header and footer are ported 1:1 from
the Next.js site (`src/app/globals.css`, `Header.tsx`, `Footer.tsx`, `public/brand/*`).

What it does

- `templates/edulage-brand/` — a drop-in `@edx/brand` package (Paragon brand override): EduLage
  palette/typography/radii/shadows as Paragon CSS variables, self-hosted Inter + Plus Jakarta Sans,
  real logo/favicon assets, and the header/footer styles (`scss/_chrome.scss`).
- `components/EdulageChrome.jsx` — React port of the site's utility bar, header (nav, study-type
  menu, search, account menu, mobile drawer), learning course strip, footer and Studio footer.
  Registered on the header/footer slots of every learner-facing MFE (legacy `PLUGIN_SLOTS`) and on
  the frontend-base shell (`FRONTEND_COMPAT_SLOTS`).
- Build pipeline: the brand package is built in a Dockerfile stage of the MFE image, installed into
  every MFE before `npm run build`, and its `dist/` is also served by Caddy at
  `https://apps.<LMS_HOST>/brand` for runtime theme URLs (`PARAGON_THEME_URLS`, frontend-base
  `theme`).
- If `tutor-indigo` is enabled, its MFE styling (brand, footer/logo slots, theme URLs) is removed
  so the two do not fight; Indigo's legacy LMS/Studio theme is kept.

Settings (all have defaults): `EDULAGE_THEME_SITE_URL`, `EDULAGE_THEME_BRAND_URL`,
`EDULAGE_THEME_TAGLINE`, `EDULAGE_THEME_COPYRIGHT`, `EDULAGE_THEME_PARAGON_CDN`.

Usage

```bash
pip install ./tutor-edulage-theme
tutor plugins enable edulage-theme
tutor config save
tutor images build mfe      # needs ~16 GB RAM; build off-box and `docker load` on the pilot
tutor local launch -I
```

Local check of the brand package alone:

```bash
cd tutor-edulage-theme/tutoredulagetheme/templates/edulage-brand
npm ci && npm run build     # -> dist/core.min.css, dist/light.min.css, fonts, images, logos
```
