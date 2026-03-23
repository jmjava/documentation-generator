"""Pipeline orchestrator: tts -> manim -> vhs -> compose -> validate -> concat -> pages."""

from __future__ import annotations

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
    ) -> None:
        if not skip_tts:
            print("\n=== Stage: TTS ===")
            from docgen.tts import TTSGenerator
            TTSGenerator(self.config).generate()

        print("\n=== Stage: Timestamps ===")
        from docgen.timestamps import TimestampExtractor
        TimestampExtractor(self.config).extract_all()

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

        print("\n=== Stage: Compose ===")
        from docgen.compose import Composer
        Composer(self.config).compose_segments(self.config.segments_all)

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
