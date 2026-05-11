This segment is about how we document the documentation generator itself. We use long-form Manim segments: scripted narration becomes audio, timestamps drive the pacing of boxes and transitions on screen, and compose plus validation finish the clip.

Maintainers add hint files under docs demos hints. Those files are normal Markdown in Git. They steer the language model when we generate narration or declarative scene YAML. They are not machine-written outputs. You wire which segment reads which hints in docgen dot yaml. For this repo, segment zero four is the only segment that pulls the dedicated hint paths. Segments zero one through zero three still rely on the top-level README and AGENTS context only.

Declarative scene specs mean the model emits YAML rows of boxes. Docgen compiles that into safe Manim layout. If you need custom motion beyond stacked boxes, add hand-maintained Manim in the scenes module outside the generated marker blocks.

When you rebuild demos, run docgen from the bundle directory next to docgen dot yaml. Commit hint files alongside config so CI and reviewers see the same steering the model sees.
