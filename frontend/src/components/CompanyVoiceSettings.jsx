import { useEffect, useState } from 'react';
import { api } from '../api';
import { Button } from './ui/Button';

export default function CompanyVoiceSettings() {
  const [voice, setVoice] = useState('');
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  useEffect(() => {
    let active = true;
    api.get('/settings/llm-voice').then(data => {
      if (active) { setVoice(data.company_voice); setReady(true); }
    }).catch(error => { if (active) setStatus(error.message); });
    return () => { active = false; };
  }, []);
  async function save(event) {
    event.preventDefault(); setBusy(true); setStatus('');
    try { await api.put('/settings/llm-voice', { company_voice: voice }); setStatus('Saved'); }
    catch (error) { setStatus(error.message || 'Could not save voice'); }
    finally { setBusy(false); }
  }
  return <section id="settings-company-voice" className="mb-10 scroll-mt-6">
    <form onSubmit={save} className="space-y-3">
      <label className="block font-semibold">LLM Company Voice
        <textarea rows={7} maxLength={20000} disabled={!ready} className="block w-full border rounded p-3 mt-2 bg-white dark:bg-gray-800" value={voice} onChange={e => setVoice(e.target.value)} />
      </label>
      <p className="text-sm text-gray-500">Global writing rules for your LLM. Use alongside the campaign’s Sequence LLM Voice.</p>
      <Button type="submit" disabled={!ready || busy}>{busy ? 'Saving…' : 'Save company voice'}</Button>
      <span role="status" className="ml-3">{status}</span>
    </form>
  </section>;
}
