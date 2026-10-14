"""One-time preservation of the original lead-level LinkedIn drafts."""
import json
from datetime import datetime, timezone
from sqlalchemy import text


async def migrate_manual_steps(conn):
    # Keep an exact archive, including ambiguous/non-enrolled leads; never guess a campaign.
    await conn.execute(text('''CREATE TABLE IF NOT EXISTS legacy_linkedin_archive (
        lead_id INTEGER PRIMARY KEY, payload JSON NOT NULL)'''))
    legacy = await conn.scalar(text("""SELECT EXISTS(SELECT 1 FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name='lead' AND column_name='linkedin_messages')"""))
    if not legacy:
        return
    once = await conn.execute(text("""INSERT INTO _app_schema_migrations(id)
        VALUES ('20261014_manual_linkedin_steps') ON CONFLICT DO NOTHING RETURNING id"""))
    if once.first() is None:
        return
    rows = (await conn.execute(text("""SELECT id, linkedin_messages, linkedin_paused, linkedin_replied_at
        FROM lead WHERE linkedin_messages::text NOT IN ('[]', 'null')
        OR linkedin_paused OR linkedin_replied_at IS NOT NULL"""))).mappings().all()
    targets = {}
    for row in rows:
        payload = dict(row)
        await conn.execute(text('''INSERT INTO legacy_linkedin_archive(lead_id,payload)
            VALUES (:id,CAST(:payload AS JSON)) ON CONFLICT DO NOTHING'''),
            {'id': row['id'], 'payload': json.dumps(payload, default=str)})
        enrollments = (await conn.execute(text('SELECT id,campaign_id FROM campaign_lead WHERE lead_id=:id'),
            {'id': row['id']})).mappings().all()
        if len(enrollments) == 1:
            targets.setdefault(enrollments[0]['campaign_id'], []).append((enrollments[0]['id'], row))
    for campaign_id, leads in targets.items():
        slots = sorted({i for _, row in leads for i,item in enumerate(row['linkedin_messages'] or [])
                        if item.get('message','').strip() or item.get('sent_at')})
        position = await conn.scalar(text('SELECT COALESCE(MAX(position),-1)+1 FROM sequence WHERE campaign_id=:id'), {'id': campaign_id})
        for offset,index in enumerate(slots):
            # Appending ignored manual steps preserves existing email positions and timing.
            sequence_id = await conn.scalar(text("""INSERT INTO sequence(campaign_id,position,body,
                wait_days_after_previous,sequence_type,manual_mode) VALUES (:campaign,:position,'',0,'linkedin','ignore') RETURNING id"""),
                {'campaign':campaign_id, 'position':position+offset})
            for cl_id, row in leads:
                messages = row['linkedin_messages'] or []
                if index >= len(messages):
                    continue
                item = messages[index]
                if not item.get('message','').strip() and not item.get('sent_at'):
                    continue
                sent_at = datetime.fromisoformat(item['sent_at'].replace('Z','+00:00')) if item.get('sent_at') else None
                if sent_at and sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                await conn.execute(text('''INSERT INTO manual_step_record(campaign_lead_id,sequence_id,message,sent_at,ignored)
                    VALUES (:cl,:step,:message,:sent_at,:ignored)'''),
                    {'cl':cl_id, 'step':sequence_id, 'message':item.get('message',''), 'sent_at':sent_at,
                     'ignored':bool(row['linkedin_paused'] or row['linkedin_replied_at'])})
    # No live/API model references these columns now. Archived values survive this removal.
    for column in ('linkedin_messages','linkedin_paused','linkedin_replied_at'):
        await conn.execute(text(f'ALTER TABLE lead DROP COLUMN IF EXISTS {column}'))
