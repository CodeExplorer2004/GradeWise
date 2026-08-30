import asyncio

from app.core.database import SessionLocal
from app.core.seed import reseed_demo_scores


async def main() -> None:
    async with SessionLocal() as session:
        updated = await reseed_demo_scores(session)
    print(f"Updated {updated} demo score rows and cleared stale risk snapshots.")


if __name__ == "__main__":
    asyncio.run(main())
