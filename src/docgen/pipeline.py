"""Pipeline orchestrator: tts -> timestamps -> scene retime -> manim -> compose -> validate.

The Manim stage renders only scenes referenced by ``visual_map`` for active ``segments.all``
entries (see :meth:`docgen.config.Config.pipeline_manim_scene_names`). Segments whose visuals
are pre-recorded (``recordings/*.mp4``) do not run through Manim capture here.

After timestamps, existing ``animations/specs/*.scene.yaml`` files are **retime-compiled**
against fresh ``timing.json`` (no OpenAI) so ``wait_word`` indices stay aligned. Optional
``regen_scene_specs`` runs LLM ``scene-spec-generate`` for manim segments before that compile.
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
        retry_manim_on_freeze: bool = False,
        regen_scene_specs: bool = False,
        skip_scene_retime: bool = False,
    ) -> None:
        if not skip_tts:
            print("\n=== Stage: TTS ===")
            from docgen.tts import TTSGenerator
            TTSGenerator(self.config).generate()

        print("\n=== Stage: Timestamps ===")
        from docgen.timestamps import TimestampExtractor
        TimestampExtractor(self.config).extract_all()

        if not skip_manim and not skip_scene_retime:
            self._run_scene_stages(regen_scene_specs=regen_scene_specs)

        if not skip_manim:
            from docgen.image_generate import generate_missing_images_for_bundle
            image_msgs = generate_missing_images_for_bundle(self.config)
            if image_msgs:
                print("\n=== Stage: Image assets ===")
                for msg in image_msgs:
                    print(f"[image-generate] {msg}")

            scene_list = self.config.pipeline_manim_scene_names()
            if scene_list:
                print("\n=== Stage: Manim ===")
                from docgen.manim_runner import ManimRunner
                ManimRunner(self.config).render(scenes=scene_list)
            else:
                print("\n=== Stage: Manim (skipped — no manim segments in visual_map) ===")

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

    def _manim_segment_ids(self) -> list[str]:
        ids: list[str] = []
        for seg_id in self.config.segments_all:
            vm = self.config.visual_map.get(seg_id)
            if isinstance(vm, dict) and str(vm.get("type", "")).strip().lower() == "manim":
                ids.append(str(seg_id))
            elif isinstance(vm, dict) and not str(vm.get("type", "")).strip():
                # Untyped but has a scene class — treat as manim for regen.
                if vm.get("scene") or vm.get("class"):
                    ids.append(str(seg_id))
        return ids

    def _run_scene_stages(self, *, regen_scene_specs: bool) -> None:
        if regen_scene_specs:
            manim_ids = self._manim_segment_ids()
            if not manim_ids:
                print("\n=== Stage: Scene-spec generate (skipped — no manim segments) ===")
                return
            print("\n=== Stage: Scene-spec generate (LLM) ===")
            from docgen.manim_scene_support import SceneGenerationError
            from docgen.scene_spec_generate import (
                generate_scene_spec,
                inject_class_block_into_scenes_py,
                linted_class_block_from_spec,
            )

            failures: list[str] = []
            for sid in manim_ids:
                print(f"[scene-spec-generate] segment {sid}")
                try:
                    res = generate_scene_spec(
                        self.config, sid, extra_paths=[], extra_hints=[]
                    )
                    specs_dir = self.config.animations_dir / "specs"
                    specs_dir.mkdir(parents=True, exist_ok=True)
                    wpath = specs_dir / f"{res.seg_name}.scene.yaml"
                    wpath.write_text(res.yaml_text, encoding="utf-8")
                    class_block, merged = linted_class_block_from_spec(
                        self.config, res.spec, timing_key=res.seg_name
                    )
                    inject_class_block_into_scenes_py(
                        self.config,
                        seg_id=merged["segment_id"],
                        class_name=merged["class_name"],
                        class_block=class_block,
                    )
                    print(f"[scene-spec-generate] wrote {wpath.name} → {merged['class_name']}")
                except (SceneGenerationError, OSError, ValueError) as exc:
                    print(f"[scene-spec-generate] FAIL {sid}: {exc}")
                    failures.append(sid)
            if failures:
                raise RuntimeError(
                    "scene-spec-generate failed for: " + ", ".join(failures)
                )
            return

        # Default: offline retime of existing declarative specs against fresh timing.
        from docgen.scene_retime import list_scene_spec_paths, retime_compile_all

        paths = list_scene_spec_paths(self.config)
        if not paths:
            print("\n=== Stage: Scene retime (skipped — no animations/specs/*.scene.yaml) ===")
            return

        print("\n=== Stage: Scene retime (compile specs against timing.json) ===")
        results, errors = retime_compile_all(self.config)
        for res in results:
            print(
                f"[scene-retime] {res['path'].name} → {res['class_name']} "
                f"(timing_key {res.get('timing_key')!r})"
            )
        for err in errors:
            print(f"[scene-retime] FAIL {err}")
        if errors:
            raise RuntimeError(
                f"scene retime failed for {len(errors)} spec(s); "
                "fix unmatched labels (spoken phrases) or set pace: none, then re-run"
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
