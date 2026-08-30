import asyncio

from app.core.database import SessionLocal
from app.core.seed import reseed_additional_grade_scores


async def main() -> None:
    async with SessionLocal() as session:
        updated = await reseed_additional_grade_scores(session)
    print(f"Updated {updated} grade-one/two demo score rows.")


if __name__ == "__main__":
    asyncio.run(main())
