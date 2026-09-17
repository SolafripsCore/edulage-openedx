#!/usr/bin/env python3
"""
One-off extraction of platform-plugin-edulage into the brand-neutral platform-plugin-campus
(core `campus_platform` + optional `campus_marketplace`). Mechanical renames only; the
structural split (hooks, marketplace app) is finished by hand afterwards.
"""
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "platform-plugin-edulage" / "edulage_platform"
DST_ROOT = ROOT / "platform-plugin-campus"
DST = DST_ROOT / "campus_platform"

if DST_ROOT.exists():
    shutil.rmtree(DST_ROOT)
shutil.copytree(SRC, DST, ignore=shutil.ignore_patterns("__pycache__"))
(DST / "templates" / "campus_platform").parent.mkdir(exist_ok=True)
shutil.move(str(DST / "templates" / "edulage_platform"), str(DST / "templates" / "campus_platform"))

RENAMES = [
    (r"edulage_platform", "campus_platform"),
    (r"EDULAGE_", "CAMPUS_"),
    (r"EdulagePlatformConfig", "CampusPlatformConfig"),
    (r"EdulageOpenIdConnect", "CampusOpenIdConnect"),
    (r"EdulageCertificate", "CampusCertificate"),
    (r"sync_edulage_identity", "sync_campus_identity"),
    (r"sync_edulage_roles", "sync_campus_roles"),
    (r'"edulage:', '"campus:'),
    (r"\^edulage/", "^campus/"),
    (r"/edulage/", "/campus/"),
    (r"edulage_sub", "identity_sub"),
    (r"edulage_roles", "campus_roles"),
    (r"edulage_status", "campus_status"),
    (r"edulage_register", "campus_register"),
    (r"edulage_staff", "campus_staff"),
    (r"edulage-staff", "campus-staff"),
    (r"edulage_integration", "campus_integration"),
    (r"edulage-integration", "campus-integration"),
    (r"edulage-lms-console", "campus-lms-console"),
    (r'name = "edulage"', 'name = "campus"'),
    (r'namespace": "edulage"', 'namespace": "campus"'),
    (r"/auth/login/edulage/", "/auth/login/campus/"),
    (r'dispatch_uid="edulage_', 'dispatch_uid="campus_'),
    (r'log\.(info|warning|error)\("edulage:', r'log.\1("campus:'),
    (r"edulage_certificate_config", "campus_certificate_config"),
    (r"edulage_email", "campus_email"),
]

for path in DST.rglob("*"):
    if path.is_dir() or path.suffix not in {".py", ".html", ".txt"}:
        continue
    text = path.read_text()
    for pat, rep in RENAMES:
        text = re.sub(pat, rep, text)
    path.write_text(text)

for path in list(DST.rglob("*edulage*")):
    path.rename(path.with_name(path.name.replace("edulage", "campus")))

(DST_ROOT / "pyproject.toml").write_text(
    """[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "platform-plugin-campus"
version = "1.0.0"
description = "Brand-neutral multi-institution campus integration for Open edX: tenancy, OIDC SSO, admission-gated enrolment, integration API, events."
license = {text = "AGPL-3.0-only"}
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
marketplace = []

[project.entry-points."lms.djangoapp"]
campus_platform = "campus_platform.apps:CampusPlatformConfig"
campus_marketplace = "campus_marketplace.apps:CampusMarketplaceConfig"

[project.entry-points."cms.djangoapp"]
campus_platform = "campus_platform.apps:CampusPlatformConfig"
campus_marketplace = "campus_marketplace.apps:CampusMarketplaceConfig"

[tool.setuptools.packages.find]
include = ["campus_platform*", "campus_marketplace*"]

[tool.setuptools.package-data]
campus_platform = ["templates/**/*.html", "templates/**/*.txt"]
campus_marketplace = ["templates/**/*.html", "templates/**/*.txt"]
"""
)
print("extracted to", DST_ROOT)
