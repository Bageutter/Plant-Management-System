(() => {
  const input = document.getElementById('ai-question');
  if (!input) return;
  const menu = document.createElement('div');
  menu.id = 'henny-plant-mentions';
  menu.setAttribute('role', 'listbox');
  menu.setAttribute('aria-label', 'Choose a plant');
  menu.style.cssText = 'display:none;position:fixed;z-index:10000;background:#fffdf7;border:1px solid #cddac3;border-radius:12px;box-shadow:0 8px 30px #18391c25;padding:6px;max-height:260px;overflow:auto';
  document.body.append(menu);
  input.setAttribute('aria-controls', menu.id);
  input.setAttribute('aria-autocomplete', 'list');
  let plants, loading, matches = [], active = 0, token;
  const normal = s => s.toLowerCase().replace(/[^a-z0-9]/g, '');
  function distance(a, b) {
    let row = Array.from({length:b.length + 1}, (_, i) => i);
    for (let i = 1; i <= a.length; i++) {
      const next = [i];
      for (let j = 1; j <= b.length; j++) next[j] = Math.min(next[j-1]+1,row[j]+1,row[j-1]+(a[i-1] !== b[j-1]));
      row = next;
    }
    return row[b.length];
  }
  function score(name, query) {
    const n = normal(name), q = normal(query);
    if (!q) return 0;
    if (n.startsWith(q)) return 100;
    if (n.includes(q)) return 80;
    const d = Math.min(...name.split(/[\s-]+/).map(w => distance(normal(w),q)));
    return d <= Math.max(1, Math.floor(q.length / 3)) ? 60-d : -1;
  }
  function hide() { menu.style.display = 'none'; input.setAttribute('aria-expanded','false'); input.removeAttribute('aria-activedescendant'); }
  function choose(index) {
    const plant = matches[index];
    if (!plant || !token) return;
    const start = token.index + token[1].length;
    const end = input.selectionStart;
    input.value = input.value.slice(0,start) + plant.name + ' ' + input.value.slice(end);
    const caret = start + plant.name.length + 1;
    input.dispatchEvent(new Event('input',{bubbles:true}));
    input.focus(); input.setSelectionRange(caret,caret); hide();
  }
  function render() {
    menu.replaceChildren();
    matches.forEach((plant,i) => {
      const option = document.createElement('div');
      option.id = `henny-plant-option-${i}`;
      option.setAttribute('role','option'); option.setAttribute('aria-selected', String(i === active));
      option.textContent = plant.name;
      option.style.cssText = `padding:9px 12px;border-radius:7px;cursor:pointer;color:#24452c;background:${i === active ? '#e8efdc' : 'transparent'}`;
      option.addEventListener('pointerdown', e => {e.preventDefault();choose(i);});
      menu.append(option);
    });
    if (!matches.length) { const label = document.createElement('p');label.textContent = 'No matching plants. Try another name.';label.style.padding = '8px';menu.append(label); }
    const rect = input.getBoundingClientRect();
    menu.style.width = `${rect.width}px`;menu.style.left = `${rect.left}px`;
    menu.style.display = 'block';menu.style.top = `${Math.max(8,rect.top - Math.min(260,menu.scrollHeight) - 8)}px`;
    input.setAttribute('aria-expanded','true');
    if (matches.length) input.setAttribute('aria-activedescendant',`henny-plant-option-${active}`);
  }
  async function update() {
    const prefix = input.value.slice(0,input.selectionStart);
    token = /(^|\s)@([^@\n,?!]*)$/.exec(prefix);
    if (!token) {hide(); return;}
    if (!plants) {
      loading ||= (async () => {
        const script = document.querySelector('script[src*="henny-mentions.js"]');
        const base = new URL('../api/catalogue',script.src);
        base.search = 'kind=plant&limit=50';
        const items = [];
        while (true) {
          const response = await fetch(base);
          if (!response.ok) throw new Error('Catalogue unavailable');
          const page = await response.json(); items.push(...page.items);
          if (page.next_offset == null) break;
          base.searchParams.set('offset',page.next_offset);
        }
        return items;
      })().catch(() => {loading = null; return null;});
      plants = await loading;
      if (!plants) {hide();return;}
      return update();
    }
    matches = plants.map(p => ({...p,score:score(p.name,token[2])})).filter(p=>p.score>=0).sort((a,b)=>b.score-a.score || a.name.localeCompare(b.name)).slice(0,7);
    active = 0;render();
  }
  input.addEventListener('input', update);
  input.addEventListener('click',update);
  input.addEventListener('keydown', e => {
    if (menu.style.display === 'none') return;
    if (['ArrowDown','ArrowUp','Enter','Escape','Tab'].includes(e.key)) {
      if (e.key === 'Tab') {hide();return;}
      e.preventDefault();e.stopImmediatePropagation();
      if (e.key === 'Escape') hide();
      else if (e.key === 'Enter') choose(active);
      else if (matches.length) {active=(active+(e.key==='ArrowDown'?1:-1)+matches.length)%matches.length;render();}
    }
  },true);
  input.addEventListener('blur',hide);
  window.addEventListener('resize',hide);
  window.addEventListener('scroll',hide,true);
})();
