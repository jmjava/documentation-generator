"""Pipeline orchestrator: tts -> manim -> vhs -> compose -> validate -> concat -> pages."""

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
        skip_playwright_tests: bool = False,
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
            print("\n=== Stage: Manim ===")
            from docgen.manim_runner import ManimRunner
            ManimRunner(self.config).render()

        if not skip_vhs:
            print("\n=== Stage: VHS ===")
            from docgen.vhs import VHSRunner
            results = VHSRunner(self.config).render()
            for r in results:
                if not r.success:
                    print(f"  WARNING: {r.tape} had errors: {r.errors}")

        if not skip_playwright_tests and self._has_playwright_test_segments():
            print("\n=== Stage: Playwright Tests ===")
            from docgen.playwright_test_runner import PlaywrightTestRunner
            runner = PlaywrightTestRunner(self.config)
            test_results = runner.run_segment_tests()
            for r in test_results:
                status = "ok" if r.success else "FAIL"
                print(f"  [{status}] {r.test}")
                for e in r.errors:
                    print(f"    {e}")

            print("\n=== Stage: Trace Extraction ===")
            from docgen.playwright_trace import TraceExtractor
            TraceExtractor(self.config).extract_all()

            if self.config.sync_playwright_after_timestamps:
                print("\n=== Stage: Sync Playwright ===")
                from docgen.playwright_sync import PlaywrightSynchronizer
                PlaywrightSynchronizer(self.config).sync()

        print("\n=== Stage: Compose ===")
        from docgen.compose import ComposeError, Composer
        composer = Composer(self.config)
        try:
            composer.compose_segments(self.config.segments_all)
        except ComposeError as exc:
            if self._should_retry_manim(exc, skip_manim, retry_manim_on_freeze):
                print("\n=== Compose FREEZE GUARD detected; retrying Manim + compose once ===")
                self._clear_manim_media_cache()
                print("\n=== Stage: Manim (retry) ===")
                from docgen.manim_runner import ManimRunner
                ManimRunner(self.config).render()
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

    def _has_playwright_test_segments(self) -> bool:
        return any(
            v.get("type") == "playwright_test"
            for v in self.config.visual_map.values()
        )

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
