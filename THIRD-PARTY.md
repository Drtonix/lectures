# Third-party components

The MIT license in `LICENSE` covers the code in this repository only. The
distributed `.app` bundle also contains the components below. Their full
license texts are inside the bundle, in `Contents/Resources/Лицензии`.

## Bundled in the application

| Component | Version | License | Source |
|---|---|---|---|
| Qt (via PySide6) | 6.11.2 | LGPL-3.0 | https://download.qt.io/official_releases/QtForPython/ |
| FFmpeg | 7.1 | LGPL-2.1-or-later | https://ffmpeg.org/releases/ffmpeg-7.1.tar.xz |
| CPython | 3.12.14 | PSF-2.0 | https://github.com/astral-sh/python-build-standalone |
| MLX, mlx-lm, mlx-whisper | 0.32.3 / 0.31.3 / 0.4.3 | MIT | https://github.com/ml-explore/mlx |
| Transformers, huggingface-hub | 5.17.0 / 1.33.0 | Apache-2.0 | https://github.com/huggingface/transformers |
| NumPy, SoundFile, Numba | 2.5.3 / 0.14.0 / 0.67.0 | BSD | https://numpy.org |
| PyObjC (Vision, Quartz) | 12.2.2 | MIT | https://github.com/ronaldoussoren/pyobjc |

FFmpeg is built from unmodified upstream sources with `--disable-autodetect`
and no GPL components enabled, so it is distributed under LGPL-2.1. The exact
configure flags are in `build_app.sh`; the source tarball is at the URL above.

Qt and FFmpeg are dynamically linked. To relink the application against your
own build of either, replace the libraries in
`Lectures.app/Contents/Resources/python/lib/python3.12/site-packages/PySide6`
or the binaries in `Lectures.app/Contents/Resources/app/bin`.

## Neural network weights

Downloaded by the user from the Settings tab on first use, and never
redistributed with the application:

| Model | License | Source |
|---|---|---|
| Whisper large-v3 | MIT | https://huggingface.co/openai/whisper-large-v3 |
| Qwen3.5-9B, Qwen3.6-35B-A3B | Apache-2.0 | https://huggingface.co/Qwen |
