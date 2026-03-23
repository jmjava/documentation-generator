Once your narration scripts are ready, docgen tts generates audio.

The TTS command reads each narration markdown file, strips all formatting, headings, bold markers, backtick code, links, stage directions, and horizontal rules. What remains is plain spoken text, exactly what the voice model will say.

You can preview the stripping without calling the API. docgen tts dry-run shows the cleaned text and character count for every segment. This is useful for estimating audio length and catching any metadata that leaked through.

When you run it for real, docgen calls OpenAI gpt-4o-mini-tts with the voice and instructions from your config. Each segment produces an MP3 in the audio directory. The file name matches the narration stem, so 01-overview dot md becomes 01-overview dot mp3.

If you change a single segment, use docgen tts segment 01 to regenerate just that one. The rest of the pipeline, Manim, VHS, compose, then picks up the new audio length automatically.

Narration lint runs as part of validation. It catches patterns that should never reach TTS: duration metadata, visual descriptions, section markers, and any remaining markdown syntax. Fix those before generating audio to avoid robotic-sounding artifacts.
