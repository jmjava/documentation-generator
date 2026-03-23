The wizard is a local web GUI that helps you draft narration scripts from your existing project documentation.

Run docgen wizard and it launches a Flask server on localhost. The interface has two main views: Setup and Production.

In Setup, you see a file tree of your repository. Select the files that are relevant to your demo. These become context for the LLM when generating narration. The wizard respects exclude patterns from docgen dot yaml, so node modules, cache directories, and build artifacts are filtered out automatically.

Switch to Production and you see every segment listed with its status. Click a segment to load its narration in the editor. You can write narration manually or have the LLM draft it from the selected context files.

The editor is a plain textarea because narration should be plain spoken English, not formatted markdown. When you save, the text is written back to the narration file on disk. When you click approve, the segment status updates and the progress bar advances.

The wizard stores its state in a dot docgen-state dot json file. This tracks which segments are approved, which need revision, and any notes. The file is local to the project and excluded from git by default.
