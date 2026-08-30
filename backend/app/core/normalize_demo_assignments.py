import asyncio

from app.core.database import SessionLocal
from app.core.seed import normalize_demo_teaching_assignments


async def main() -> None:
    async with SessionLocal() as session:
        updated = await normalize_demo_teaching_assignments(session)
    print(f"Rebuilt {updated} demo teaching assignments with one fixed subject per teacher.")


if __name__ == "__main__":
    asyncio.run(main())
