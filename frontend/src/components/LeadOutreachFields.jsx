import Dropdown from './ui/Dropdown';
import { useState } from 'react';
import { api } from '../api';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

const inputClass = 'block w-full rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 p-2 mt-1';
export default function LeadOutreachFields({ lead, onSaved }) {
  const [form, setForm] = useState(() => ({
    priority: lead.priority || 'normal', company: lead.company || '', job_title: lead.job_title || '',
    role_description: lead.role_description || '', apollo_id: lead.apollo_id || '',
    notes: lead.notes || '', linkedin_url: lead.linkedin_url || '',
  }));
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [savedProfile, setSavedProfile] = useState(form);
  const change = (key, value) => setForm(old => ({ ...old, [key]: value }));
  async function save(event) {
    event.preventDefault(); setBusy(true); setStatus('');
    try {
      const payload = Object.fromEntries(Object.entries(form).filter(([key, value]) => value !== savedProfile[key]));
      await api.patch(`/leads/${lead.id}`, payload);
      setSavedProfile({ ...form });
      setStatus('Saved');
      onSaved?.();
    } catch (error) { setStatus(error.message || 'Could not save lead'); }
    finally { setBusy(false); }
  }
  return <Card className="p-4 space-y-5">
    <h2 className="text-lg font-semibold">Lead profile & LinkedIn</h2>
    <form onSubmit={save} className="space-y-4">
      <label className="block">Priority<Dropdown className={inputClass} value={form.priority} onChange={e => change('priority', e.target.value)}>
        {['low', 'normal', 'high'].map(value => <option key={value} value={value}>{value}</option>)}
      </Dropdown></label>
      {['job_title', 'company', 'apollo_id'].map(key => <label className="block" key={key}>{key === 'job_title' ? 'Job title' : key === 'company' ? 'Company' : 'Apollo ID'}
        <input className={inputClass} maxLength={255} value={form[key]} onChange={e => change(key, e.target.value)} />
      </label>)}
      {['role_description', 'notes'].map(key => <label className="block" key={key}>{key === 'notes' ? 'Notes' : 'Role description'}
        <textarea className={inputClass} rows={4} maxLength={key === 'notes' ? 50000 : 20000} value={form[key]} onChange={e => change(key, e.target.value)} />
      </label>)}
      <fieldset className="space-y-3">
        <legend className="font-semibold">LinkedIn</legend>
        <label className="block">Profile URL<input type="url" className={inputClass} maxLength={2048} placeholder="https://www.linkedin.com/in/…" value={form.linkedin_url} onChange={e => change('linkedin_url', e.target.value)} /></label>
      </fieldset>
      <p className="text-sm text-gray-500">Last tracked email sent: {lead.last_email_sent_at ? new Date(lead.last_email_sent_at).toLocaleString() : 'None recorded'}</p>
      <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save profile & notes'}</Button>
      <span role="status" className="ml-3 text-sm">{status}</span>
    </form>
  </Card>;
}
