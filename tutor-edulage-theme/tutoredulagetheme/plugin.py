"""
EduLage theme for Open edX (Tutor plugin).

Makes learn.edulage.org / apps.learn.edulage.org / studio.edulage.org visually identical to
edulage.org (Next.js): same tokens, fonts, header, footer, buttons and spacing. It does not
touch Open edX core; everything goes through supported extension points:

* Paragon design tokens (CSS custom properties), fonts and logos built from
  ``templates/edulage-brand`` inside the MFE image as a drop-in ``@edx/brand`` package (bundled
  into every MFE at build time) and also served at ``/brand`` for runtime consumers.
* Header/footer replaced via frontend-plugin-framework slots with React components in
  ``components/``.
* Legacy LMS/CMS pages themed by the ``edulage`` comprehensive theme in ``templates/edulage``.
"""

from __future__ import annotations

import json
import os
from glob import glob

import importlib_resources
from tutor import hooks
from tutormfe.hooks import FRONTEND_COMPAT_SLOTS, PLUGIN_SLOTS

from .__init__ import __version__

PKG = importlib_resources.files("tutoredulagetheme")

########################################
# Configuration
########################################

hooks.Filters.CONFIG_DEFAULTS.add_items(
    [
        ("EDULAGE_THEME_VERSION", __version__),
        # Public marketplace (discovery stays there; the LMS is "My learning").
        ("EDULAGE_THEME_SITE_URL", "https://edulage.org"),
        # Where the compiled brand CSS, fonts and logos are served from (MFE Caddy image).
        # Spelled out rather than via MFE_HOST: Tutor renders config values one level deep, and
        # MFE_HOST is itself a template. Override this if MFE_HOST is customised.
        (
            "EDULAGE_THEME_BRAND_URL",
            "{{ 'https' if ENABLE_HTTPS else 'http' }}://apps.{{ LMS_HOST }}/brand",
        ),
        ("EDULAGE_THEME_ORG_NAME", "EduLage"),
        ("EDULAGE_THEME_TAGLINE", "The Global Education Village"),
        ("EDULAGE_THEME_COPYRIGHT", "EduLage.org"),
        # Paragon version whose default core/light CSS the brand override sits on top of.
        # frontend-platform substitutes $paragonVersion with the version bundled in each MFE.
        (
            "EDULAGE_THEME_PARAGON_CDN",
            "https://cdn.jsdelivr.net/npm/@openedx/paragon@$paragonVersion/dist",
        ),
    ]
)

########################################
# Templates: brand package (MFE build context) and legacy theme
########################################

hooks.Filters.ENV_TEMPLATE_ROOTS.add_item(str(PKG / "templates"))
hooks.Filters.ENV_TEMPLATE_TARGETS.add_items(
    [
        # -> env/plugins/mfe/build/mfe/edulage-brand (Docker build context of the mfe image)
        ("edulage-brand", "plugins/mfe/build/mfe"),
        # -> env/build/openedx/themes/edulage (comprehensive theme for legacy LMS/CMS pages)
        ("edulage", "build/openedx/themes"),
    ]
)

########################################
# Patches and React components
########################################

for path in glob(os.path.join(str(PKG / "patches"), "*")):
    with open(path, encoding="utf-8") as f:
        hooks.Filters.ENV_PATCHES.add_item((os.path.basename(path), f.read()))

# Components are exposed as patches so env.config.jsx can inline them with {{ patch("X.jsx") }}.
for path in glob(os.path.join(str(PKG / "components"), "*.jsx")):
    with open(path, encoding="utf-8") as f:
        hooks.Filters.ENV_PATCHES.add_item((os.path.basename(path), f.read()))

########################################
# Runtime theme (Paragon design tokens)
########################################

PARAGON_THEME_URLS = {
    "core": {
        "urls": {
            "default": "{{ EDULAGE_THEME_PARAGON_CDN }}/core.min.css",
            "brandOverride": "{{ EDULAGE_THEME_BRAND_URL }}/core.min.css",
        }
    },
    "defaults": {"light": "light"},
    "variants": {
        "light": {
            "urls": {
                "default": "{{ EDULAGE_THEME_PARAGON_CDN }}/light.min.css",
                "brandOverride": "{{ EDULAGE_THEME_BRAND_URL }}/light.min.css",
            }
        }
    },
}

# frontend-base loads one stylesheet per layer: core = brand override on top of the shell's
# bundled Paragon core; light = full variant (Paragon light + EduLage light).
FRONTEND_BASE_THEME = {
    "core": {"url": "{{ EDULAGE_THEME_BRAND_URL }}/core.min.css"},
    "defaults": {"light": "light"},
    "variants": {"light": {"url": "{{ EDULAGE_THEME_BRAND_URL }}/light.min.css"}},
}

hooks.Filters.ENV_PATCHES.add_item(
    (
        "mfe-lms-common-settings",
        "MFE_CONFIG['PARAGON_THEME_URLS'] = "
        + json.dumps(PARAGON_THEME_URLS)
        + "\n"
        + "MFE_CONFIG['EDULAGE_SITE_URL'] = '{{ EDULAGE_THEME_SITE_URL }}'\n"
        + "MFE_CONFIG['EDULAGE_BRAND_URL'] = '{{ EDULAGE_THEME_BRAND_URL }}'\n"
        + "MFE_CONFIG['EDULAGE_TAGLINE'] = '{{ EDULAGE_THEME_TAGLINE }}'\n"
        + "MFE_CONFIG['EDULAGE_COPYRIGHT'] = '{{ EDULAGE_THEME_COPYRIGHT }}'\n"
        + "MFE_CONFIG['LOGO_URL'] = '{{ EDULAGE_THEME_BRAND_URL }}/images/edulage-logo.png'\n"
        + "MFE_CONFIG['LOGO_TRADEMARK_URL'] = MFE_CONFIG['LOGO_URL']\n"
        + "MFE_CONFIG['LOGO_WHITE_URL'] = '{{ EDULAGE_THEME_BRAND_URL }}/images/edulage-logo-white.png'\n"
        + "MFE_CONFIG['FAVICON_URL'] = '{{ EDULAGE_THEME_BRAND_URL }}/favicon.ico'\n"
        + "FRONTEND_SITE_CONFIG.setdefault('commonAppConfig', {})\n"
        + "FRONTEND_SITE_CONFIG['theme'] = "
        + json.dumps(FRONTEND_BASE_THEME)
        + "\n"
        + "FRONTEND_SITE_CONFIG['commonAppConfig']['PARAGON_THEME_URLS'] = MFE_CONFIG['PARAGON_THEME_URLS']\n"
        + "for _k in ('EDULAGE_SITE_URL', 'EDULAGE_BRAND_URL', 'EDULAGE_TAGLINE', 'EDULAGE_COPYRIGHT'):\n"
        + "    FRONTEND_SITE_CONFIG['commonAppConfig'][_k] = MFE_CONFIG[_k]\n",
    )
)

########################################
# Plugin slots (header / footer)
########################################

HIDE_DEFAULT = """
    {
        op: PLUGIN_OPERATIONS.Hide,
        widgetId: 'default_contents',
    },
"""


def _insert(widget_id: str, component: str, priority: int = 1) -> str:
    return f"""
    {{
        op: PLUGIN_OPERATIONS.Insert,
        widget: {{
            id: '{widget_id}',
            type: DIRECT_PLUGIN,
            priority: {priority},
            RenderWidget: {component},
        }},
    }},
"""


HEADER_SLOTS = (
    "org.openedx.frontend.layout.header_desktop.v1",
    "org.openedx.frontend.layout.header_mobile.v1",
)
LEARNING_HEADER_SLOT = "org.openedx.frontend.layout.header_learning.v1"
FOOTER_SLOT = "org.openedx.frontend.layout.footer.v1"
STUDIO_FOOTER_SLOT = "org.openedx.frontend.layout.studio_footer.v1"

# Legacy MFEs (built with frontend-platform) that render the learner-facing header/footer.
CHROME_MFES = [
    "learner-dashboard",
    "learning",
    "account",
    "profile",
    "discussions",
    "gradebook",
    "ora-grading",
    "communications",
]

EDULAGE_HEADER = HIDE_DEFAULT + _insert("edulage_header", "EdulageHeader")
EDULAGE_FOOTER = HIDE_DEFAULT + _insert("edulage_footer", "EdulageFooter")

for _mfe in CHROME_MFES:
    for _slot in HEADER_SLOTS:
        PLUGIN_SLOTS.add_item((_mfe, _slot, EDULAGE_HEADER))
    PLUGIN_SLOTS.add_item((_mfe, FOOTER_SLOT, EDULAGE_FOOTER))
PLUGIN_SLOTS.add_item(
    (
        "learning",
        LEARNING_HEADER_SLOT,
        HIDE_DEFAULT + _insert("edulage_header", "EdulageLearningHeader"),
    )
)
PLUGIN_SLOTS.add_item(
    ("authoring", STUDIO_FOOTER_SLOT, HIDE_DEFAULT + _insert("edulage_footer", "EdulageStudioFooter"))
)

# frontend-base applications (instructor-dashboard, notifications, ...) render the shell's
# header/footer; the compat shim maps these legacy slot ids onto the shell sub-slots.
for _slot in HEADER_SLOTS:
    FRONTEND_COMPAT_SLOTS.add_item(("all", _slot, EDULAGE_HEADER))
FRONTEND_COMPAT_SLOTS.add_item(("all", FOOTER_SLOT, EDULAGE_FOOTER))


########################################
# Coexistence with tutor-indigo
########################################
# Indigo may stay enabled for its legacy LMS/CMS theme, but its MFE contributions (brand
# install, footer/logo/header slots, runtime theme URLs) would fight with EduLage's. They are
# removed once all plugins are loaded; the Indigo legacy theme (openedx-* patches) is kept.


@hooks.Actions.PLUGINS_LOADED.add()
def _supersede_indigo_mfe_styling() -> None:
    if "indigo" not in list(hooks.Filters.PLUGINS_LOADED.iterate()):
        return
    indigo = hooks.Contexts.app("indigo").name
    indigo_patches = {
        (name, content)
        for name, content in hooks.Filters.ENV_PATCHES.iterate_from_context(indigo)
        if name.startswith("mfe-") or name.endswith(".jsx")
    }
    indigo_slots = set(PLUGIN_SLOTS.iterate_from_context(indigo))
    indigo_compat_slots = set(FRONTEND_COMPAT_SLOTS.iterate_from_context(indigo))
    # Some Indigo slots are registered lazily (outside its plugin context, e.g. the themed
    # logo); recognise those by the components they render.
    indigo_components = ("IndigoFooter", "ThemedLogo", "MobileViewHeader", "ToggleThemeButton", "AddDarkTheme")

    def _is_indigo(slot: tuple[str, str, str]) -> bool:
        return any(c in slot[2] for c in indigo_components)

    @hooks.Filters.ENV_PATCHES.add(priority=hooks.priorities.LOW)
    def _drop_indigo_mfe_patches(
        patches: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        return [p for p in patches if p not in indigo_patches]

    @PLUGIN_SLOTS.add(priority=hooks.priorities.LOW)
    def _drop_indigo_slots(
        slots: list[tuple[str, str, str]]
    ) -> list[tuple[str, str, str]]:
        return [s for s in slots if s not in indigo_slots and not _is_indigo(s)]

    @FRONTEND_COMPAT_SLOTS.add(priority=hooks.priorities.LOW)
    def _drop_indigo_compat_slots(
        slots: list[tuple[str, str, str]]
    ) -> list[tuple[str, str, str]]:
        return [s for s in slots if s not in indigo_compat_slots and not _is_indigo(s)]

    # Indigo registers PARAGON_THEME_URLS as a config default; ours must win.
    hooks.Filters.CONFIG_DEFAULTS.add_item(("PARAGON_THEME_URLS", PARAGON_THEME_URLS))


########################################
# Build fix: Debian bullseye is EOL
########################################
# The upstream MFE image is based on node:20-bullseye-slim, whose live mirrors no longer serve
# the bullseye-security pool, so the `apt install` in the base stage fails. Pin apt to the
# snapshot.debian.org sources that the image itself ships (commented out) before that install.
# Remove once tutor-mfe moves off bullseye.
BULLSEYE_APT_RUN = "RUN apt update \\\n"
BULLSEYE_APT_FIX = (
    "RUN sed -i -e 's|^# deb http://snapshot|deb http://snapshot|' -e '/deb.debian.org/d' /etc/apt/sources.list \\\n"
    "  && echo 'Acquire::Check-Valid-Until false;' > /etc/apt/apt.conf.d/99snapshot \\\n"
    "  && apt update \\\n"
)


@hooks.Actions.ENV_SAVED.add()
def _pin_bullseye_apt_sources(root_env: str, _config: dict[str, object]) -> None:
    path = os.path.join(root_env, "plugins", "mfe", "build", "mfe", "Dockerfile")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if "bullseye" not in content or BULLSEYE_APT_FIX in content:
        return
    content = content.replace(BULLSEYE_APT_RUN, BULLSEYE_APT_FIX, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
