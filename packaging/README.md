# Packaging the desktop GUI

The freeze target is **`docgen-gui`**: a Vue window over the local Flask
wizard (benchmark view first). It is **not** a frozen copy of the full
`docgen` CLI (Manim / ffmpeg / OpenAI stay on the pip tool).

```bash
pip install -e '.[packaging]'
docgen freeze                 # writes dist/docgen-gui/docgen-gui
docgen freeze --smoke         # freeze, then headless GET / and /api/benchmark
# equivalent: pyinstaller packaging/docgen-gui.spec
```

From a source checkout you can run the same entry without freezing:

```bash
pip install -e '.[gui]'
docgen gui                 # pywebview window if the extra is installed
docgen gui --browser       # system browser fallback
docgen gui --config path/to/docgen.yaml
docgen benchmark --gui
python -m docgen.gui
```

Asset paths use ``docgen.resources.package_root()`` so templates, static
Vue files, and ``benchmark_data/`` resolve both in an editable install and
under ``sys._MEIPASS`` after PyInstaller.
