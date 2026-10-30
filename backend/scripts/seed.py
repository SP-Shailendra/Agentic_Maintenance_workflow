"""Idempotently seed PostgreSQL demo assets, inventory, technicians, and manuals."""

import asyncio
import json
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from app.datapulse.simulator import load_assets
from app.foundation.db import create_database_engine
from app.foundation.models import assets, manual_chunks, parts_inventory, technicians
from app.grounding.chunker import load_manual_corpus

ROOT = Path(__file__).resolve().parents[2]


async def seed() -> None:
    engine = create_database_engine()
    try:
        asset_rows = [asset.model_dump(mode="python") for asset in load_assets()]
        parts = json.loads((ROOT / "data" / "seed" / "parts.json").read_text(encoding="utf-8"))
        techs = json.loads(
            (ROOT / "data" / "seed" / "technicians.json").read_text(encoding="utf-8")
        )
        chunks = [
            {
                "asset_class": chunk.asset_class,
                "fault_code": chunk.fault_code,
                "document": chunk.document,
                "section": chunk.section,
                "content": chunk.content,
            }
            for chunk in load_manual_corpus()
        ]
        async with engine.begin() as connection:
            await connection.execute(
                insert(assets)
                .values(asset_rows)
                .on_conflict_do_update(
                    index_elements=[assets.c.asset_id],
                    set_={
                        key: getattr(insert(assets).excluded, key)
                        for key in asset_rows[0]
                        if key != "asset_id"
                    },
                )
            )
            await connection.execute(
                insert(parts_inventory)
                .values(parts)
                .on_conflict_do_update(
                    index_elements=[parts_inventory.c.part_number],
                    set_={
                        key: getattr(insert(parts_inventory).excluded, key)
                        for key in parts[0]
                        if key != "part_number"
                    },
                )
            )
            await connection.execute(
                insert(technicians)
                .values(techs)
                .on_conflict_do_update(
                    index_elements=[technicians.c.technician_id],
                    set_={
                        key: getattr(insert(technicians).excluded, key)
                        for key in techs[0]
                        if key != "technician_id"
                    },
                )
            )
            await connection.execute(delete(manual_chunks))
            await connection.execute(insert(manual_chunks).values(chunks))
        print(
            f"Seeded {len(asset_rows)} assets, {len(parts)} parts, "
            f"{len(techs)} technicians, {len(chunks)} manual chunks"
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())