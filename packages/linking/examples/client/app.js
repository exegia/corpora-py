import {makeLinkClient, selectedEndpoint} from './linking-client.js';

const element = (id) => document.getElementById(id);
const config = await (await fetch('/demo/config')).json();
const links = makeLinkClient({apiUrl: location.origin, spaceId: config.spaceId,
  getAccessToken: () => element('actor').value});
element('source').value = config.source.text;
element('target').value = config.target.text;
let draft = null;
let current = null;
let busy = false;

function selections() {
  return {source: selectedEndpoint(config.source, element('source')),
    target: selectedEndpoint(config.target, element('target'))};
}
function showCurrent() {
  const reference = current.reference;
  element('states').textContent = `Resolution: ${reference.resolution} · Review: ${reference.review} · Publication: ${reference.publication}`;
  element('record').textContent = JSON.stringify(current, null, 2);
  for (const id of ['open', 'approve', 'stale']) element(id).disabled = false;
}
async function run(action) {
  if (busy) return;
  busy = true;
  const buttons = [...document.querySelectorAll('button')];
  const disabled = buttons.map(button => button.disabled);
  buttons.forEach(button => button.disabled = true);
  try {await action();} catch (error) {
    element('status').textContent = `${error.status ? error.status + ': ' : ''}${error.message}`;
  } finally {
    busy = false;
    buttons.forEach((button, index) => button.disabled = disabled[index]);
    if (current) showCurrent();
  }
}
element('sample').onclick = () => {
  for (const [id, text] of [['source', 'The linked passage'], ['target', 'A verse-like destination']]) {
    const textarea = element(id);
    const start = textarea.value.indexOf(text);
    textarea.setSelectionRange(start, start + text.length);
  }
  element('status').textContent = 'Example passages selected. Preview or save them.';
};
element('preview').onclick = () => run(async () => {
  const endpoints = selections();
  const from = await links.retrieve(endpoints.source);
  const to = await links.retrieve(endpoints.target);
  element('previewText').textContent = `From: ${from.text}\nTo: ${to.text}`;
  element('status').textContent = 'Both exact selections verified.';
});
element('save').onclick = () => run(async () => {
  const endpoints = selections();
  if (!draft) draft = {id: crypto.randomUUID(), ...endpoints, relationship: 'core:cites',
    provenance: {origin: 'manual', agent_id: 'client-placeholder', method: 'reader-selection'}};
  draft = {...draft, ...endpoints};
  const saved = await links.save(draft, current?.version ?? null);
  current = await links.latest(saved.reference.id);
  element('status').textContent = 'Link saved — waiting for review.';
});
element('open').onclick = () => run(async () => {
  await links.decide(current.reference.id, 'resolve', current.version, 'Check selected destination');
  current = await links.latest(current.reference.id);
  if (current.reference.resolution !== 'resolved') throw new Error('Destination needs review or a fresh selection.');
  const result = await links.retrieve(current.reference.target);
  element('destination').textContent = result.text;
  element('status').textContent = 'Exact destination opened.';
});
element('approve').onclick = () => run(async () => {
  await links.decide(current.reference.id, 'approve', current.version, 'Checked both selections');
  current = await links.latest(current.reference.id);
  element('status').textContent = 'Link approved. Publication is still draft.';
});
element('stale').onclick = () => run(async () => {
  const changed = {...current.reference.target, revision: 'demo-version-2'};
  try {await links.retrieve(changed);} catch (error) {
    if (error.status !== 422) throw error;
    element('status').textContent = 'Passed: a changed document version was rejected.';
    return;
  }
  throw new Error('Failed: a stale selection was accepted.');
});
