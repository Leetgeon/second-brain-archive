# -*- mode: python ; coding: utf-8 -*-

import os
import sys
import json
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files


project_root = Path(SPECPATH).parent
source_root = project_root / "src"
generated_root = project_root / "build" / "generated"
generated_root.mkdir(parents=True, exist_ok=True)
profile_path = generated_root / "distribution_profile.json"
profile = os.environ.get("SECOND_BRAIN_PROFILE", "public")
profile_path.write_text(
    '{"profile": "%s"}\n' % profile,
    encoding="utf-8",
)
homepage_url = os.environ.get("SECOND_BRAIN_HOMEPAGE_URL", "").rstrip("/")
source_public_info_path = source_root / "second_brain_archive" / "public_info.json"
source_public_info = json.loads(source_public_info_path.read_text(encoding="utf-8"))
homepage_url = (
    homepage_url
    or str(source_public_info.get("homepage_url", "")).rstrip("/")
)


def env_or_default(name, default):
    return os.environ.get(name, "").strip() or default


public_info_path = generated_root / "public_info.json"
public_info_path.write_text(
    json.dumps(
        {
            "app_name": env_or_default(
                "SECOND_BRAIN_APP_NAME",
                source_public_info.get("app_name", "Second Brain Archive"),
            ),
            "operator_name": env_or_default(
                "SECOND_BRAIN_OPERATOR_NAME",
                source_public_info.get("operator_name", ""),
            ),
            "support_email": env_or_default(
                "SECOND_BRAIN_SUPPORT_EMAIL",
                source_public_info.get("support_email", ""),
            ),
            "homepage_url": homepage_url,
            "privacy_url": env_or_default(
                "SECOND_BRAIN_PRIVACY_URL",
                source_public_info.get(
                    "privacy_url",
                    f"{homepage_url}/privacy/" if homepage_url else "",
                ),
            ),
            "terms_url": env_or_default(
                "SECOND_BRAIN_TERMS_URL",
                source_public_info.get(
                    "terms_url",
                    f"{homepage_url}/terms/" if homepage_url else "",
                ),
            ),
            "jurisdiction": env_or_default(
                "SECOND_BRAIN_JURISDICTION",
                source_public_info.get("jurisdiction", "Republic of Korea"),
            ),
        },
        ensure_ascii=False,
    ),
    encoding="utf-8",
)

binaries = []
datas = collect_data_files("second_brain_archive")
datas.append((str(profile_path), "second_brain_archive"))
datas.append((str(public_info_path), "second_brain_archive"))
hiddenimports = []
bundled_packages = (
    ("imageio_ffmpeg", "yt_dlp")
    if profile == "personal"
    else ()
)
for package in bundled_packages:
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

analysis = Analysis(
    [str(project_root / "packaging" / "desktop_entry.py")],
    pathex=[str(source_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=(
        ["imageio_ffmpeg", "yt_dlp"]
        if profile == "public"
        else []
    ),
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Second Brain Archive",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=os.environ.get("APPLE_SIGNING_IDENTITY"),
    entitlements_file=None,
)
bundle_files = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Second Brain Archive",
)

if sys.platform == "darwin":
    application = BUNDLE(
        bundle_files,
        name="Second Brain Archive.app",
        bundle_identifier="com.secondbrain.archive",
        version="0.2.0",
        info_plist={
            "CFBundleDisplayName": "Second Brain Archive",
            "CFBundleShortVersionString": "0.2.0",
            "NSHighResolutionCapable": True,
        },
    )
