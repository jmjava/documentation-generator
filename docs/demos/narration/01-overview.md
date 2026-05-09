Docgen is a powerful documentation generator designed to create narrated demo videos using Python. It focuses on two primary tools: Manim for long-form storytelling and Playwright for creating tutorials from UI tests.

The library provides a command-line interface and a reusable Python library to streamline the process of generating video documentation. It allows users to create engaging content that explains how a system works, making it easier to understand complex concepts.

Docgen emphasizes a modern approach to video documentation. It supports scripted narration that can be generated from Markdown scripts using text-to-speech technology. This narration is paired with visuals created in Manim, which serves as the main medium for explaining architecture and workflows. Playwright can be integrated where interactive browser demonstrations are necessary.

The library provides a suite of features, including validation checks for audio-visual sync, layout analysis, and error detection. It also includes a local web GUI wizard to help bootstrap narration scripts from existing project documentation, making it user-friendly for newcomers.

Legacy support for VHS terminal recordings exists, but users are encouraged to migrate to using Manim and Playwright for new projects. This shift not only improves the quality of the documentation but also aligns with modern development practices.

Installation is straightforward, allowing users to quickly set up their environment with a simple command. Development workflows are flexible, with the ability to run tests and manage dependencies easily.

Overall, Docgen offers a comprehensive solution for generating high-quality documentation and narrated demo videos, ensuring that both developers and end-users have access to clear, informative content.
