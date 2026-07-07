"""Build the release zip: PyInstaller exe + bilingual usage guides.

Usage:  py -3.12 build_release.py
Output: release/CultistAdviser-v<version>.zip

Release checklist (after this script):
  1. gh release create v<version> release/CultistAdviser-v<version>.zip \
       --title v<version> --notes "..."
  2. Release notes are BILINGUAL: Chinese sections first, then an
     "## English" section summarizing the same changes.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from cultist_adviser import __version__  # noqa: E402

ROOT = Path(__file__).parent
GUIDES = [ROOT / "dist_extra" / "使用说明.txt",
          ROOT / "dist_extra" / "User Guide.txt"]
LEX_CACHE = ROOT / "cultist_adviser" / "lexicon_cache.json"
LEX_BUNDLED = ROOT / "cultist_adviser" / "lexicon_cache_bundled.json"
KN_CACHE = ROOT / "cultist_adviser" / "knowledge_cache.json"
KN_BUNDLED = ROOT / "cultist_adviser" / "knowledge_cache_bundled.json"


def _refresh_bundled_caches():
    """Regenerate lexicon and knowledge caches from the build machine's game
    install, then snapshot them as *_bundled.json — those get baked into
    the exe as a fallback for users whose game path can't be auto-detected."""
    from cultist_adviser import lexicon, knowledge
    for cache in (LEX_CACHE, KN_CACHE):
        cache.unlink(missing_ok=True)
    lexicon._load()
    knowledge._load()
    if not LEX_CACHE.exists() or lexicon.size() < lexicon._HEALTHY_MIN:
        sys.exit(f"lexicon rebuild yielded only {lexicon.size()} entities — "
                 "the build machine must have a working game install")
    shutil.copy2(LEX_CACHE, LEX_BUNDLED)
    if KN_CACHE.exists():
        shutil.copy2(KN_CACHE, KN_BUNDLED)
    print(f"bundled lexicon ({lexicon.size()} entities) and knowledge caches")


def main():
    for guide in GUIDES:
        if not guide.exists():
            sys.exit(f"missing guide: {guide}")
        head = guide.read_text(encoding="utf-8").splitlines()[0]
        if __version__ not in head:
            sys.exit(f"{guide.name} first line says '{head}' — bump it to v{__version__}")

    _refresh_bundled_caches()

    subprocess.run([sys.executable, "-m", "PyInstaller", "CultistAdviser.spec",
                    "--noconfirm", "--distpath", "dist"], check=True, cwd=ROOT)

    out = ROOT / "release" / f"CultistAdviser-v{__version__}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(ROOT / "dist" / "CultistAdviser.exe", "CultistAdviser.exe")
        for guide in GUIDES:
            z.write(guide, guide.name)
    print(f"\nbuilt {out}")
    print("next: gh release create — remember BILINGUAL notes (中文 + ## English)")


if __name__ == "__main__":
    main()
