"""Annotate thumbnails with a VLM (Claude vision) using a hard-edge schema.

Thumb aesthetics modulo (brightness/contrast/colorfulness/face_pct) cobre
low-level. Faltam atributos de packaging que so um modelo de visao enxerga:
"tem texto sobreposto?", "rosto reativo ou neutro?", "estetica
found-footage ou slasher?".

Schema 6-attribute deliberadamente *hard-edge* (binaria ou enum curto)
pra reduzir variancia entre runs do mesmo modelo no mesmo image:

  has_text_overlay   : bool
  face_emotion       : reactive | neutral | absent
  composition_style  : reaction | cinematic | collage | screenshot | other
  color_palette      : high_saturation | desaturated | monochrome | red_dominant
  has_subject_arrow  : bool
  subgenre_signal    : found_footage | slasher | gore | paranormal | crime | other

Output persistido em `thumb_attributes`. Resume-able: pula video_ids ja
anotados (`force=False`).
"""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import duckdb

from jason.config import get_settings

logger = logging.getLogger(__name__)


SCHEMA_VERSION = "v1"

_SYSTEM_PROMPT = """Voce e um classificador visual especializado em thumbnails de YouTube de canais brasileiros de terror/analise de filmes.

Para CADA imagem que receber, retorne UM objeto JSON estritamente neste schema:

{
  "has_text_overlay": <bool: existe texto grande sobreposto na imagem? (titulo, "EXPLICADO", "FINAL", numero, etc)>,
  "face_emotion": <"reactive" se rosto humano com expressao forte (boca aberta, susto, raiva, choro), "neutral" se rosto sem expressao forte, "absent" se sem rosto humano>,
  "composition_style": <"reaction" se foco em rosto humano em primeiro plano, "cinematic" se frame de filme com atmosfera, "collage" se multiplas imagens lado a lado, "screenshot" se aparenta print de cena/pagina, "other">,
  "color_palette": <"high_saturation" se cores vivas/saturadas, "desaturated" se cores mortas/cinzas, "monochrome" se preto-e-branco ou tons unicos, "red_dominant" se vermelho/sangue dominante>,
  "has_subject_arrow": <bool: existe seta, circulo, ou marca apontando pra algo na imagem?>,
  "subgenre_signal": <"found_footage" se camera amadora/VHS, "slasher" se mascara/lamina/serial-killer, "gore" se sangue/violencia explicita, "paranormal" se sobrenatural/fantasma/possessao, "crime" se evidencia policial/processo/jornalistico, "other">
}

Sem comentarios, sem markdown, sem texto fora do JSON. UM objeto por imagem na ordem em que receber.
"""


def _read_pending(
    con: duckdb.DuckDBPyConnection, *, force: bool, channel_id: str | None,
) -> list[tuple[str, Path]]:
    """Returns list of (video_id, thumbnail_path_on_disk) yet-to-annotate."""
    settings = get_settings()
    tdir = settings.data_dir / "thumbnails"
    sql = ["SELECT v.id FROM videos v"]
    sql.append("LEFT JOIN thumb_attributes t ON t.video_id = v.id")
    if force:
        sql.append("WHERE 1=1")
    else:
        sql.append("WHERE t.video_id IS NULL")
    params: list[Any] = []
    if channel_id:
        sql.append("AND v.channel_id = ?")
        params.append(channel_id)
    sql.append("AND v.is_short = false")
    rows = con.execute(" ".join(sql), params).fetchall()

    pending = []
    for (vid,) in rows:
        p = tdir / f"{vid}.jpg"
        if p.exists():
            pending.append((vid, p))
    return pending


def _encode_image_b64(path: Path) -> str:
    return base64.standard_b64encode(path.read_bytes()).decode("ascii")


def _default_vlm_client(
    *, model: str = "claude-sonnet-4-6",
) -> Callable[[list[Path]], list[dict[str, Any]]]:
    """Builds a real Anthropic client. Returns a function that takes a batch
    of image paths and returns parsed annotation dicts."""
    import anthropic  # noqa: PLC0415

    client = anthropic.Anthropic()

    def annotate(paths: list[Path]) -> list[dict[str, Any]]:
        if not paths:
            return []
        content: list[dict[str, Any]] = []
        for p in paths:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": _encode_image_b64(p),
                },
            })
        content.append({
            "type": "text",
            "text": (
                f"Anote as {len(paths)} imagens acima nessa ordem. "
                "Retorne um array JSON: [obj1, obj2, ...]."
            ),
        })
        msg = client.messages.create(
            model=model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        # Extract JSON array even if wrapped in markdown.
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1].lstrip("json\n").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"VLM returned non-JSON: {text[:200]}") from exc
        if not isinstance(data, list) or len(data) != len(paths):
            raise ValueError(
                f"VLM returned {len(data) if isinstance(data, list) else type(data)} entries for {len(paths)} images"
            )
        return data

    return annotate


def _persist(
    con: duckdb.DuckDBPyConnection,
    *,
    video_ids: list[str],
    annotations: list[dict[str, Any]],
    model_version: str,
) -> int:
    """Upserts annotations into thumb_attributes."""
    if not video_ids:
        return 0
    n = 0
    for vid, ann in zip(video_ids, annotations, strict=True):
        try:
            con.execute(
                """
                INSERT INTO thumb_attributes (
                    video_id, has_text_overlay, face_emotion,
                    composition_style, color_palette, has_subject_arrow,
                    subgenre_signal, annotated_at, model_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, now(), ?)
                ON CONFLICT (video_id) DO UPDATE SET
                    has_text_overlay = EXCLUDED.has_text_overlay,
                    face_emotion = EXCLUDED.face_emotion,
                    composition_style = EXCLUDED.composition_style,
                    color_palette = EXCLUDED.color_palette,
                    has_subject_arrow = EXCLUDED.has_subject_arrow,
                    subgenre_signal = EXCLUDED.subgenre_signal,
                    annotated_at = now(),
                    model_version = EXCLUDED.model_version
                """,
                [
                    vid,
                    bool(ann.get("has_text_overlay")),
                    str(ann.get("face_emotion", "absent"))[:40],
                    str(ann.get("composition_style", "other"))[:40],
                    str(ann.get("color_palette", "other"))[:40],
                    bool(ann.get("has_subject_arrow")),
                    str(ann.get("subgenre_signal", "other"))[:40],
                    model_version,
                ],
            )
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("persist failed for %s: %s", vid, exc)
    return n


def annotate_thumbnails(
    *,
    db_path: Path | None = None,
    channel_id: str | None = None,
    force: bool = False,
    batch_size: int = 4,
    max_videos: int | None = None,
    annotate_fn: Callable[[list[Path]], list[dict[str, Any]]] | None = None,
    model_version: str = SCHEMA_VERSION,
) -> dict[str, int]:
    """Run the VLM annotator over thumbnails missing in `thumb_attributes`."""
    settings = get_settings()
    db = db_path or settings.duckdb_path

    with duckdb.connect(str(db)) as con:
        pending = _read_pending(con, force=force, channel_id=channel_id)
        if max_videos:
            pending = pending[:max_videos]
        if not pending:
            return {"requested": 0, "annotated": 0, "failed": 0}

        client = annotate_fn or _default_vlm_client()

        annotated = 0
        failed = 0
        total = len(pending)
        for i in range(0, total, batch_size):
            batch = pending[i : i + batch_size]
            ids = [vid for vid, _ in batch]
            paths = [p for _, p in batch]
            try:
                results = client(paths)
                annotated += _persist(
                    con, video_ids=ids, annotations=results,
                    model_version=model_version,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("batch %d failed: %s", i // batch_size, exc)
                failed += len(batch)
                continue
            if (i // batch_size) % 10 == 0:
                logger.info(
                    "vlm: %d/%d annotated (%d failed)",
                    annotated, total, failed,
                )

    return {
        "requested": len(pending),
        "annotated": annotated,
        "failed": failed,
    }
