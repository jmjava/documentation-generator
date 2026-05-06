This segment shows how docgen treats browser-test footage like any other visual source. You record or export a short Playwright video, point the manifest at that file, and compose muxes it with the narration audio from this repository.

The pipeline skips Manim and VHS capture for this segment because the WebM is already on disk. That keeps long-running UI tests out of the default generate-all path while still proving the playwright_test visual type end to end.
