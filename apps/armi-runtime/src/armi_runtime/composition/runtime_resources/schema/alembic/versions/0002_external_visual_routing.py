"""Preserve external visual routing and detected image properties."""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE armi.external_message_parts
          ADD COLUMN visual_role text,
          ADD COLUMN source_kind text,
          ADD COLUMN source_summary text,
          ADD COLUMN detected_media_type text,
          ADD COLUMN pixel_width integer,
          ADD COLUMN pixel_height integer,
          ADD COLUMN frame_count integer,
          ADD CONSTRAINT external_message_parts_visual_role_check CHECK (
            visual_role IS NULL OR visual_role = ANY (ARRAY[
              'ordinary','sticker','sticker_candidate','platform_special','unknown'
            ])
          ),
          ADD CONSTRAINT external_message_parts_source_kind_check CHECK (
            source_kind IS NULL OR source_kind ~ '^[a-z][a-z0-9._-]{0,63}$'
          ),
          ADD CONSTRAINT external_message_parts_source_summary_check CHECK (
            source_summary IS NULL OR octet_length(source_summary) BETWEEN 1 AND 512
          ),
          ADD CONSTRAINT external_message_parts_detected_media_type_check CHECK (
            detected_media_type IS NULL OR
            detected_media_type ~ '^[a-z0-9][a-z0-9!#$&^_.+-]{0,62}/[a-z0-9][a-z0-9!#$&^_.+-]{0,62}$'
          ),
          ADD CONSTRAINT external_message_parts_visual_shape_check CHECK (
            (part_kind <> 'image' AND visual_role IS NULL AND source_kind IS NULL
              AND source_summary IS NULL AND detected_media_type IS NULL
              AND pixel_width IS NULL AND pixel_height IS NULL AND frame_count IS NULL)
            OR
            (part_kind = 'image'
              AND ((visual_role IS NULL AND source_kind IS NULL AND source_summary IS NULL)
                   OR (visual_role IS NOT NULL AND source_kind IS NOT NULL))
              AND ((detected_media_type IS NULL AND pixel_width IS NULL
                    AND pixel_height IS NULL AND frame_count IS NULL)
                   OR (detected_media_type IS NOT NULL AND pixel_width > 0
                       AND pixel_height > 0 AND frame_count > 0
                       AND pixel_width::bigint * pixel_height::bigint <= 36000000)))
          );
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
