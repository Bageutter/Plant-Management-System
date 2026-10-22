/* Stages come from real server state/callbacks, never elapsed-time animation. */
(() => {
  const panel = document.getElementById('ai-live-progress');
  if (!panel) return;
  let active = null;
  const sets = {
    multi_agent: [['planning','Planner'],['working','Worker'],['reviewing','Reviewer'],['awaiting_human_review','Human review']],
    planning: [['plan','Plan'],['act','Act'],['observe','Observe'],['adapt','Adapt']]
  };
  const render = (job, data) => {
    const stages = sets[job.mode];
    const reached = data.phases || [];
    const current = data.phase;
    const label = stages.find(([key]) => key === current)?.[1];
    panel.querySelector('p').textContent = label ? `${label} · current stage` :
      current === 'failed' ? 'Execution failed — inspect the saved response below.' : 'Waiting for the server…';
    const list = panel.querySelector('ol');
    list.replaceChildren();
    stages.forEach(([key, title], index) => {
      const later = stages.slice(index + 1).some(([phase]) => reached.includes(phase) || phase === current);
      const state = key === current ? 'current' : later || reached.includes(key) ? 'complete' : 'pending';
      const item = document.createElement('li');
      item.className = `stage-${state}`;
      if (state === 'current') item.setAttribute('aria-current','step');
      const number = document.createElement('span'); number.textContent = String(index + 1);
      const name = document.createElement('strong'); name.textContent = title;
      const status = document.createElement('small'); status.textContent = (state === 'current' && key === 'awaiting_human_review') ? 'Awaiting your decision' : {current:'Running',complete:'Observed',pending:'Not reached'}[state];
      item.append(number, name, status); list.append(item);
    });
  };
  const poll = async job => {
    while (active === job) {
      try {
        const response = await fetch(panel.dataset.progressUrl.replace('PROGRESSID',job.id), {credentials:'same-origin', cache:'no-store', signal:job.controller.signal});
        if (response.ok) {
          const data = await response.json();
          if (active === job) render(job, data);
        } else if (response.status !== 404 && active === job) {
          panel.querySelector('p').textContent = 'Live status unavailable — the request may still be running.';
        }
      } catch (error) {
        if (active === job) panel.querySelector('p').textContent = 'Connection interrupted — waiting for real status.';
      }
      if (active === job) await new Promise(resolve => setTimeout(resolve,700));
    }
  };
  document.body.addEventListener('htmx:configRequest', event => {
    const form = event.detail.elt;
    if (!(form instanceof HTMLFormElement) || !form.querySelector('#ai-question')) return;
    const mode = event.detail.parameters.mode;
    if (!sets[mode]) return;
    if (active) active.controller.abort();
    const id = crypto.randomUUID().replaceAll('-','');
    event.detail.parameters.progress_id = id;
    active = {id,mode,form,controller:new AbortController()};
    panel.hidden = false;
    render(active,{phase:'queued',phases:[]});
    poll(active);
  });
  document.body.addEventListener('htmx:afterRequest', event => {
    if (active && event.detail.elt === active.form) {
      active.controller.abort(); active = null; panel.hidden = true;
    }
  });
})();
