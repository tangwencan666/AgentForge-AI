from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.domain.tasks import TenantUsage


async def tenant_usage(session, tenant_id, day):
    await session.execute(insert(TenantUsage).values(tenant_id=tenant_id,day=day,tokens_used=0,tokens_reserved=0,
        cost_used=Decimal(0),cost_reserved=Decimal(0)).on_conflict_do_nothing())
    return (await session.scalars(select(TenantUsage).where(TenantUsage.tenant_id==tenant_id,TenantUsage.day==day).with_for_update())).one()
