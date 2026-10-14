"""Local-only migration check. Requires an empty disposable PostgreSQL TEST_DATABASE_URL."""
import asyncio,json
from datetime import datetime,timezone
from sqlalchemy import text
from app.database import Base,engine,_run_migrations
from app import models
async def main():
 if engine.dialect.name != 'postgresql':
  raise RuntimeError('Use an empty disposable PostgreSQL database via TEST_DATABASE_URL')
 async with engine.begin() as c:
  if await c.scalar(text("SELECT to_regclass('lead')")):
   raise RuntimeError('Migration check requires an empty disposable database')
  await c.run_sync(Base.metadata.create_all)
  for col,typ in [('linkedin_messages',"JSON DEFAULT '[]'"),('linkedin_paused','BOOLEAN DEFAULT false'),('linkedin_replied_at','TIMESTAMP WITH TIME ZONE')]:
   await c.execute(text(f'ALTER TABLE lead ADD COLUMN {col} {typ}'))
  await c.execute(text('ALTER TABLE sequence DROP COLUMN manual_mode'))
  await c.execute(text('ALTER TABLE lead DROP COLUMN company'))
  for i in (1,2):
   await c.execute(models.Campaign.__table__.insert().values(id=i,name=f'Campaign{i}',public_id=f'campaign{i}'))
  for i in (1,2,3):
   await c.execute(text("INSERT INTO lead(id,email,name,notes,custom_data) VALUES (:id,:email,'Legacy','Keep',CAST(:custom AS JSON))"),{'id':i,'email':f'lead{i}@example.test','custom':json.dumps({'company':'Acme'})})
   await c.execute(text("UPDATE lead SET linkedin_messages=CAST(:data AS JSON) WHERE id=:id"),{'id':i,'data':json.dumps([{'message':'Saved draft','sent':False,'sent_at':None},{'message':'Sent text','sent':True,'sent_at':'2026-10-10T12:30:45Z'},{'message':'','sent':False,'sent_at':None}])})
  # One unambiguous lead, one multi-campaign lead, one not enrolled.
  for i,camp,lead in [(1,1,1),(2,1,2),(3,2,2)]:
   await c.execute(models.CampaignLead.__table__.insert().values(id=i,campaign_id=camp,lead_id=lead,enrollment_status='contacted'))
  await c.execute(text("INSERT INTO sequence(campaign_id,position,body,sequence_type,wait_days_after_previous) VALUES (1,0,'Email','standard',0)"))
  await _run_migrations(c)
  assert await c.scalar(text("SELECT count(*) FROM lead WHERE company='Acme'"))==3
  assert await c.scalar(text('SELECT count(*) FROM legacy_linkedin_archive')) == 3
  assert await c.scalar(text('SELECT count(*) FROM manual_step_record')) == 2
  steps=(await c.execute(text('SELECT position,sequence_type,manual_mode FROM sequence ORDER BY position'))).all()
  assert [tuple(s) for s in steps]==[(0,'standard','hold'),(1,'linkedin','ignore'),(2,'linkedin','ignore')],steps
  records=(await c.execute(text('SELECT campaign_lead_id,message,sent_at FROM manual_step_record ORDER BY sequence_id'))).all()
  assert records[0].campaign_lead_id == 1 and records[0].message=='Saved draft' and records[0].sent_at is None
  assert records[1].sent_at==datetime(2026,10,10,12,30,45,tzinfo=timezone.utc)
  assert await c.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_name='lead' AND column_name IN ('linkedin_messages','linkedin_paused','linkedin_replied_at')"))==0
  await c.execute(text("UPDATE manual_step_record SET message='Edited' WHERE sent_at IS NULL"))
  await c.execute(text("UPDATE lead SET company='' WHERE id=1"))
  await _run_migrations(c)
  assert await c.scalar(text("SELECT company FROM lead WHERE id=1"))==''
  assert await c.scalar(text('SELECT count(*) FROM sequence'))==3
  assert await c.scalar(text("SELECT count(*) FROM manual_step_record WHERE message='Edited'"))==1
  assert await c.scalar(text("SELECT count(*) FROM lead WHERE notes='Keep'"))==3
 print('PASS: old data archived; unambiguous records migrated; ignored appended steps preserve email positions; timestamps and notes preserved; repeat migration preserves edits.')
 await engine.dispose()
asyncio.run(main())
