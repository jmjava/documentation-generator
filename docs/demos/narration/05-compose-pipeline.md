This segment walks the end-to-end pipeline from words on disk to a finished segment MP4. You start from narration Markdown in the bundle, then run docgen TTS so OpenAI turns that script into speech.

Docgen timestamps aligns the audio to a fine-grained timing track using hosted speech-to-text so Manim can follow when phrases begin and end. You render the Manim scene that illustrates those ideas, then docgen compose uses ffmpeg to combine the picture and soundtrack.

After compose, docgen validate checks drift between what you heard and what the video shows, and narration lint catches patterns that are awkward for text-to-speech. When every segment is ready, docgen concat builds the full-demo reel.

That is one coherent toolchain: narration, audio, timing, diagram, mux, checks, and optional concat, without a separate browser automation layer.
