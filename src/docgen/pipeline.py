"""Pipeline orchestrator: tts -> manim -> vhs -> compose -> validate -> concat -> pages.

Manim and VHS stages render only scenes/tapes referenced by ``visual_map`` for active
``segments.all`` entries (see :meth:`docgen.config.Config.pipeline_manim_scene_names` and
:meth:`~docgen.config.Config.pipeline_vhs_tape_filenames`). Segments whose visuals are
``playwright_test`` use pre-recorded files and do not run through Manim or VHS capture here.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docgen.config import Config


class Pipeline:
    def __init__(self, config: Config) -> None:
        self.config = config

    def run(
        self,
        skip_tts: bool = False,
        skip_manim: bool = False,
        skip_vhs: bool = False,
        skip_tape_sync: bool = False,
        retry_manim_on_freeze: bool = False,
    ) -> None:
        if not skip_tts:
            print("\n=== Stage: TTS ===")
            from docgen.tts import TTSGenerator
            TTSGenerator(self.config).generate()

        print("\n=== Stage: Timestamps ===")
        from docgen.timestamps import TimestampExtractor
        TimestampExtractor(self.config).extract_all()

        if self.config.sync_vhs_after_timestamps and not skip_tape_sync:
            print("\n=== Stage: Sync VHS tape sleep timings ===")
            from docgen.tape_sync import TapeSynchronizer
            TapeSynchronizer(self.config).sync()

        if not skip_manim:
            scene_list = self.config.pipeline_manim_scene_names()
            if scene_list:
                print("\n=== Stage: Manim ===")
                from docgen.manim_runner import ManimRunner
                ManimRunner(self.config).render(scenes=scene_list)
            else:
                print("\n=== Stage: Manim (skipped — no manim segments in visual_map) ===")

        if not skip_vhs:
            tape_list = self.config.pipeline_vhs_tape_filenames()
            if tape_list:
                print("\n=== Stage: VHS ===")
                from docgen.vhs import VHSRunner
                results = VHSRunner(self.config).render(tapes=tape_list)
                for r in results:
                    if not r.success:
                        print(f"  WARNING: {r.tape} had errors: {r.errors}")
            else:
                print("\n=== Stage: VHS (skipped — no vhs segments in visual_map) ===")

        print("\n=== Stage: Compose ===")
        from docgen.compose import ComposeError, Composer
        composer = Composer(self.config)
        try:
            composer.compose_segments(self.config.segments_all)
        except ComposeError as exc:
            if self._should_retry_manim(exc, skip_manim, retry_manim_on_freeze):
                print("\n=== Compose FREEZE GUARD detected; retrying Manim + compose once ===")
                self._clear_manim_media_cache()
                scene_list = self.config.pipeline_manim_scene_names()
                if scene_list:
                    print("\n=== Stage: Manim (retry) ===")
                    from docgen.manim_runner import ManimRunner
                    ManimRunner(self.config).render(scenes=scene_list)
                print("\n=== Stage: Compose (retry) ===")
                composer.compose_segments(self.config.segments_all)
            else:
                raise

        print("\n=== Stage: Validate ===")
        from docgen.validate import Validator
        validator = Validator(self.config)
        reports = validator.run_all()
        validator.print_report(reports)

        print("\n=== Stage: Concat ===")
        from docgen.concat import ConcatBuilder
        ConcatBuilder(self.config).build()

        print("\n=== Stage: Pages ===")
        from docgen.pages import PagesGenerator
        PagesGenerator(self.config).generate_all(force=True)

        print("\n=== Pipeline complete ===")

    @staticmethod
    def _should_retry_manim(
        exc: Exception, skip_manim: bool, retry_manim_on_freeze: bool
    ) -> bool:
        if skip_manim or not retry_manim_on_freeze:
            return False
        return "FREEZE GUARD" in str(exc).upper()

    def _clear_manim_media_cache(self) -> None:
        media_dir = self.config.animations_dir / "media"
        if not media_dir.exists():
            print("[pipeline] Manim cache already empty")
            return
        shutil.rmtree(media_dir)
        print(f"[pipeline] Cleared Manim cache: {media_dir}")
