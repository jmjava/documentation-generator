Docgen is a documentation generator for narrated demo videos in Python. The workflow centers on Manim for diagrams and animation, paired with Markdown narration that becomes audio through OpenAI text-to-speech.

The library provides a command-line interface and a reusable Python library so teams can standardize how they turn code and architecture into watchable explainers. You describe ideas in prose, render visuals in Manim, align them with timestamps from the real voice track, then compose and validate before publishing.

Docgen emphasizes a modern approach to video documentation. Scripted narration can be generated or edited as Markdown, converted to speech, and synchronized with Manim scenes that explain architecture and workflows. Validation and narration lint help keep audio and picture in step.

Installation is straightforward, workflows are flexible, and the same commands run locally or in continuous integration.

Overall, docgen is aimed at teams that want high-quality, repeatable video documentation without maintaining a separate browser-capture stack inside this tool.
