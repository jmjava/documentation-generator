Composition is where audio meets video. docgen compose takes the TTS audio and the visual source for each segment and produces a final MP4.

The visual map in docgen dot yaml tells compose where to find each segment's video. A segment can be a Manim animation, a VHS terminal recording, a mix of both, a still image, or a solid color background.

When the video is shorter than the audio, compose freezes the last frame to fill the gap. This looks natural, like a pause on the final visual. When the video is longer, it trims to match the audio length. The result is always a clean mux with synchronized streams.

After composing, validation runs automatically. docgen validate checks every recording for three things. First, that both audio and video streams are present. Second, that the duration drift between streams is within your configured threshold, default two point seven five seconds. Third, that the narration source file passes lint.

Use docgen validate pre-push for a strict gate. It exits non-zero on any failure, so CI and pre-push hooks can block bad recordings from reaching the repository.

Finally, docgen concat assembles individual segments into a full demo file according to your concat configuration. You can define multiple concat targets, for example a core demo and an extended version with extra segments.
