import { useState } from 'react';
import { api } from '../api';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

const inputClass = 'block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 p-2 mt-1';
const localDate = (value) => {
  if (!value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

function LinkedInMessage({ leadId, position, initial }) {
  const [message, setMessage] = useState(initial?.message || '');
  const [sent, setSent] = useState(initial?.sent || false);
  const [sentAt, setSentAt] = useState(localDate(initial?.sent_at));
  const [saved, setSaved] = useState({ message: initial?.message || '', sent: initial?.sent || false, sent_at: initial?.sent_at });
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  async function save(event) {
    event.preventDefault(); setBusy(true); setStatus('');
    try {
      const payload = {};
      if (message !== saved.message) payload.message = message;
      if (sent !== saved.sent) payload.sent = sent;
      if (sent && sentAt && sentAt !== localDate(saved.sent_at)) payload.sent_at = new Date(sentAt).toISOString();
      const result = await api.patch(`/leads/${leadId}/linkedin/${position}`, payload);
      setSent(result.sent); setSentAt(localDate(result.sent_at)); setSaved(result); setMessage(result.message); setStatus('Saved');
    } catch (error) { setStatus(error.message || 'Could not save message'); }
    finally { setBusy(false); }
  }
  return <form onSubmit={save} className="space-y-3 border-t pt-4">
    <label className="block">LinkedIn message {position} (optional)
      <textarea className={inputClass} rows={3} maxLength={10000} value={message} onChange={e => setMessage(e.target.value)} />
    </label>
    <label className="flex gap-2 items-center"><input type="checkbox" checked={sent} onChange={e => {
      setSent(e.target.checked); if (!e.target.checked) setSentAt('');
    }} />Message sent</label>
    {sent && <label className="block">Sent at (local time; blank preserves the recorded time or uses now for a new send)
      <input type="datetime-local" className={inputClass} value={sentAt} onChange={e => setSentAt(e.target.value)} />
    </label>}
    <Button type="submit" disabled={busy}>{busy ? 'Saving…' : `Save message ${position}`}</Button>
    <span role="status" className="ml-3 text-sm">{status}</span>
  </form>;
}

export default function LeadOutreachFields({ lead }) {
  const [form, setForm] = useState(() => ({
    priority: lead.priority || 'normal', job_title: lead.job_title || '',
    role_description: lead.role_description || '', apollo_id: lead.apollo_id || '',
    notes: lead.notes || '', linkedin_url: lead.linkedin_url || '',
    linkedin_paused: lead.linkedin_paused || false, linkedin_replied_at: localDate(lead.linkedin_replied_at),
  }));
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [savedProfile, setSavedProfile] = useState(form);
  const change = (key, value) => setForm(old => ({ ...old, [key]: value }));
  async function save(event) {
    event.preventDefault(); setBusy(true); setStatus('');
    try {
      const payload = Object.fromEntries(Object.entries(form).filter(([key, value]) => value !== savedProfile[key]));
      if ('linkedin_replied_at' in payload) payload.linkedin_replied_at = form.linkedin_replied_at ? new Date(form.linkedin_replied_at).toISOString() : null;
      await api.patch(`/leads/${lead.id}`, payload);
      setSavedProfile({ ...form });
      setStatus('Saved');
    } catch (error) { setStatus(error.message || 'Could not save lead'); }
    finally { setBusy(false); }
  }
  return <Card className="p-4 space-y-5">
    <h2 className="text-lg font-semibold">Lead profile & LinkedIn</h2>
    <form onSubmit={save} className="space-y-4">
      <label className="block">Priority<select className={inputClass} value={form.priority} onChange={e => change('priority', e.target.value)}>
        {['low', 'normal', 'high'].map(value => <option key={value} value={value}>{value}</option>)}
      </select></label>
      {['job_title', 'apollo_id'].map(key => <label className="block" key={key}>{key === 'job_title' ? 'Job title' : 'Apollo ID'}
        <input className={inputClass} maxLength={255} value={form[key]} onChange={e => change(key, e.target.value)} />
      </label>)}
      {['role_description', 'notes'].map(key => <label className="block" key={key}>{key === 'notes' ? 'Notes' : 'Role description'}
        <textarea className={inputClass} rows={4} maxLength={key === 'notes' ? 50000 : 20000} value={form[key]} onChange={e => change(key, e.target.value)} />
      </label>)}
      <fieldset className="space-y-3">
        <legend className="font-semibold">LinkedIn</legend>
        <label className="block">Profile URL<input type="url" className={inputClass} maxLength={2048} placeholder="https://www.linkedin.com/in/…" value={form.linkedin_url} onChange={e => change('linkedin_url', e.target.value)} /></label>
        <label className="flex gap-2 items-center"><input type="checkbox" checked={form.linkedin_paused} onChange={e => change('linkedin_paused', e.target.checked)} />Pause LinkedIn outreach</label>
        <label className="block">LinkedIn replied at (local time)<input type="datetime-local" className={inputClass} value={form.linkedin_replied_at} onChange={e => change('linkedin_replied_at', e.target.value)} /></label>
      </fieldset>
      <p className="text-sm text-gray-500">Last tracked email sent: {lead.last_email_sent_at ? new Date(lead.last_email_sent_at).toLocaleString() : 'None recorded'}</p>
      <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save profile & notes'}</Button>
      <span role="status" className="ml-3 text-sm">{status}</span>
    </form>
    <p className="text-sm text-gray-500">Optional drafts and manual send records. Saving or marking sent does not send a LinkedIn message.</p>
    {[1, 2, 3].map(position => <LinkedInMessage key={position} leadId={lead.id} position={position} initial={lead.linkedin_messages?.[position - 1]} />)}
  </Card>;
}
