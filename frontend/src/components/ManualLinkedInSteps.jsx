import { useEffect, useState } from 'react';
import { api } from '../api';
import { Button } from './ui/Button';

const inputClass = 'block w-full rounded border border-gray-300 bg-white p-2 mt-1';
const localDate = value => {
  if (!value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

export function ManualLinkedInFields({ value, onChange }) {
  return <div className="space-y-4">
    <p className="text-sm text-gray-600">Send this message yourself in LinkedIn, then mark it sent here. Nothing is sent automatically.</p>
    <label className="block">Manual step behavior<select className={inputClass} value={value.manual_mode || 'hold'} onChange={e => onChange({ manual_mode: e.target.value })}>
      <option value="hold">Hold — wait until completed or ignored</option>
      <option value="ignore">Ignore — emails continue without waiting</option>
    </select></label>
    <label className="block">LinkedIn draft (optional)<textarea className={inputClass} rows={5} maxLength={10000} value={value.body || ''} onChange={e => onChange({ body: e.target.value })} /></label>
    <p className="text-xs text-gray-500">Each lead can have a different message. Hold pauses later steps; Ignore lets emails continue while this message stays Pending or Done.</p>
  </div>;
}

function LeadManualStep({ campaignId, initial }) {
  const [saved, setSaved] = useState(initial);
  const [form, setForm] = useState({ message: initial.message || '', sent: initial.sent, ignored: initial.ignored, sent_at: localDate(initial.sent_at) });
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const change = (key, value) => setForm(old => ({ ...old, [key]: value }));
  async function save(event) {
    event.preventDefault(); setBusy(true); setStatus('');
    try {
      const payload = {};
      for (const key of ['message', 'sent', 'ignored']) if (form[key] !== saved[key]) payload[key] = form[key];
      if (form.sent && form.sent_at && form.sent_at !== localDate(saved.sent_at)) payload.sent_at = new Date(form.sent_at).toISOString();
      const result = await api.patch(`/campaigns/${campaignId}/leads/${initial.lead_id}/manual-steps/${initial.sequence_id}`, payload);
      setSaved(result);
      setForm({ message: result.message || '', sent: result.sent, ignored: result.ignored, sent_at: localDate(result.sent_at) });
      setStatus('Saved');
    } catch (error) { setStatus(error.message || 'Could not save manual step'); }
    finally { setBusy(false); }
  }
  return <form onSubmit={save} className="border rounded-lg p-4 space-y-3" aria-label={`LinkedIn for ${initial.email}`}>
    <div><strong>{initial.name || initial.email}</strong> <span className="text-sm text-gray-500">{initial.email} · {initial.priority} priority</span></div>
    <p className="text-sm">{saved.sent ? 'Done' : 'Pending'} · {saved.ignored ? 'Ignored' : saved.mode === 'ignore' ? 'Does not hold email' : saved.sent ? 'Completed' : saved.ready ? 'Ready — waiting for manual completion' : 'Not ready'}</p>
    {initial.linkedin_url && /^https:\/\/([a-z0-9-]+\.)*linkedin\.com\//i.test(initial.linkedin_url) && <a className="text-teal-700 underline" href={initial.linkedin_url} target="_blank" rel="noreferrer">Open LinkedIn profile</a>}
    <fieldset disabled={busy} className="space-y-3">
    <label className="block">Message<textarea className={inputClass} rows={4} maxLength={10000} value={form.message} onChange={e => change('message', e.target.value)} /></label>
    <label className="block">Status<select className={inputClass} value={form.sent ? 'done' : 'pending'} onChange={e => setForm(old => ({ ...old, sent: e.target.value === 'done', sent_at: e.target.value === 'done' ? old.sent_at : '' }))}>
      <option value="pending">Pending</option><option value="done">Done — sent</option>
    </select></label>
    {form.sent && <label className="block">Sent at (local time; blank preserves the time or uses now)<input type="datetime-local" className={inputClass} value={form.sent_at} onChange={e => change('sent_at', e.target.value)} /></label>}
    <label className="flex items-center gap-2"><input type="checkbox" checked={!!form.ignored} onChange={e => change('ignored', e.target.checked)} />Ignore for this lead</label>
    <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save manual step'}</Button>
    </fieldset>
    <span role="status" className="ml-3 text-sm">{status}</span>
  </form>;
}

export default function ManualLinkedInSteps({ campaignId, sequence }) {
  const [records, setRecords] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    api.get(`/campaigns/${campaignId}/manual-steps?sequence_id=${sequence.id}`).then(data => { if (active) setRecords(data.filter(row => row.sequence_id === sequence.id)); }).catch(error => { if (active) setError(error.message); });
    return () => { active = false; };
  }, [campaignId, sequence.id]);
  return <section className="space-y-4">
    <h4 className="font-semibold">Manual LinkedIn · {sequence.manual_mode === 'ignore' ? 'Ignore' : 'Hold'}</h4>
    <p className="text-sm text-gray-600">{sequence.manual_mode === 'ignore' ? 'Emails continue without waiting for this step. Pending messages remain available to complete manually.' : 'Later steps wait until this step is marked sent/completed or ignored for the lead.'} Send messages yourself in LinkedIn. Undoing completion cannot recall emails already sent.</p>
    {error && <p role="alert" className="text-red-600">{error}</p>}
    {!records && !error && <p>Loading manual steps…</p>}
    {records?.length === 0 && <p>No enrolled leads.</p>}
    {records?.map(record => <LeadManualStep key={`${record.campaign_lead_id}-${record.sequence_id}`} campaignId={campaignId} initial={record} />)}
  </section>;
}
