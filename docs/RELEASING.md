# Release process

## 1. Prepare

- Update the version in `pyproject.toml`, `src/faco_voicetype/__init__.py`, `faco_module.json`, and `faco_capabilities.json`.
- Update user-facing version text in installer and upgrade scripts.
- Move completed entries from `Unreleased` into a dated changelog section.
- Confirm README and canonical-layout documentation still match the installer.

## 2. Validate

```bash
PYTHONPATH=src pytest -q
python -m compileall -q src tests selftest.py
for script in *.sh scripts/*.sh; do bash -n "$script"; done
python selftest.py
```

Run the suite three consecutive times for a final release. Exercise the full installer in an isolated non-root environment with:

- a legacy installation path containing spaces;
- a canonical FACO root containing spaces;
- an existing runtime and state to migrate;
- networking unavailable for the first dependency pass;
- both installer Enter prompts;
- verification that the old runtime is removed only after successful canonical validation.

Record the results in `RELEASE_TEST_LOG.txt` and update `VALIDATION.md` if the scope changes.

## 3. Build the release archive

```bash
./scripts/build_release.sh
```

The script writes a versioned `.tar.gz` and SHA-256 file to `dist/`, then verifies the checksum and archive contents.

## 4. Verify the exact archive

Extract the archive into a fresh temporary directory and repeat compilation, Bash syntax, and the full automated test suite from that extracted copy. Do not publish a package that differs from the package tested.

## 5. Publish

- Commit the release documentation and validated source.
- Create an annotated `vX.Y.Z` tag from the validated commit.
- Create a GitHub Release using `.github/RELEASE_TEMPLATE.md`.
- Attach the `.tar.gz` and `.sha256` files.
- Confirm the repository default branch, release page, source archive, checksum, license, and CI result are public and readable.
