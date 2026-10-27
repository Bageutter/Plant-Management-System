(function () {
  'use strict';
  function calculatePlan(v) {
    for (const key of ['grams','people','weeks','yieldGrams','windowWeeks','intervalDays']) {
      if (!Number.isFinite(v[key]) || v[key] <= 0) throw new Error('Enter a positive number in every required field.');
    }
    if (![v.people,v.weeks,v.intervalDays].every(Number.isInteger)) throw new Error('People, weeks and sowing days must be whole numbers.');
    const weeklyGrams = v.grams * v.people;
    const intervalWeeks = v.intervalDays / 7;
    const minimumOverlap = Math.floor(v.windowWeeks / intervalWeeks + 1e-9);
    const firstBatch = Math.ceil(weeklyGrams * v.windowWeeks / v.yieldGrams);
    const plantsPerBatch = Math.ceil(weeklyGrams * v.windowWeeks / (v.yieldGrams * Math.max(1, minimumOverlap)));
    const batchCount = Math.ceil(v.weeks / intervalWeeks);
    return {weeklyGrams, firstBatch, plantsPerBatch, batchCount,
      totalPlants: firstBatch + (batchCount - 1) * plantsPerBatch,
      gapDays: Math.max(0, v.intervalDays - v.windowWeeks * 7),
      minimumOverlap, totalTargetGrams: weeklyGrams * v.weeks};
  }
  const monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  function seasonalSchedule(v, plan, start, months, maturityDays) {
    const allowed = new Set(months.map(m=>monthNames.indexOf(m)).filter(m=>m>=0));
    const date = new Date(start+'T12:00:00Z');
    if (!Number.isFinite(date.getTime())) throw new Error('Choose a sowing date.');
    let moved = 0;
    while (allowed.size && !allowed.has(date.getUTCMonth()) && moved < 366) {date.setUTCDate(date.getUTCDate()+1); moved++;}
    const rows = [], skipped = [];
    for (let i=0;i<plan.batchCount;i++) {
      const sow = new Date(date); sow.setUTCDate(sow.getUTCDate()+i*v.intervalDays);
      if (allowed.size && !allowed.has(sow.getUTCMonth())) {skipped.push(sow.toISOString().slice(0,10)); continue;}
      rows.push({sow:sow.toISOString().slice(0,10), offset:i*v.intervalDays, plants:i===0?plan.firstBatch:plan.plantsPerBatch});
    }
    let shortDays = null;
    if (maturityDays > 0) {
      // Compare each day of the supply period with the yield from active batches.
      shortDays = 0;
      for (let day=0;day<v.weeks*7;day++) {
        const grams = rows.reduce((sum,row)=>sum+(day>=row.offset && day<row.offset+v.windowWeeks*7 ? row.plants*v.yieldGrams/(v.windowWeeks*7) : 0),0);
        if (grams+1e-6<plan.weeklyGrams/7) shortDays++;
      }
    }
    return {rows,skipped,moved,shortDays,seasonRecorded:allowed.size>0,totalPlants:rows.reduce((n,r)=>n+r.plants,0)};
  }
  function recordedMaturity(notes) {
    const match = notes.match(/(?:about\s+)?(\d+)\s*(?:[–-]\s*(\d+)\s*)?days?\s+(?:from sowing\s+)?(?:to|until)\s+(?:the\s+)?first harvest/i);
    return match ? Number(match[2] || match[1]) : null;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {calculatePlan, seasonalSchedule, recordedMaturity};
  if (typeof document === 'undefined') return;
  const tool = document.getElementById('harvest-calculator');
  if (!tool) return;
  const form = tool.querySelector('form');
  const field = name => form.elements.namedItem(name);
  const recordedYield = Number(tool.dataset.yield);
  field('yieldGrams').value = recordedYield > 0 ? recordedYield * (tool.dataset.unit === 'kg' ? 1000 : 1) : '';
  const months = JSON.parse(tool.dataset.months || '[]');
  const maturityFromRecord = recordedMaturity(JSON.parse(tool.dataset.harvestNotes || '""'));
  field('maturityDays').value = maturityFromRecord || '';
  field('windowWeeks').value = tool.dataset.window;
  field('intervalDays').value = tool.dataset.interval;
  const today = new Date();
  field('start').value = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  document.getElementById('harvest-data-note').textContent = recordedYield > 0 ? 'Yield and harvest window start from this plant’s saved catalogue. You can adjust them.' : 'No usable weight yield is recorded for this plant. Enter your own yield and harvest window to calculate.';
  const result = document.getElementById('harvest-plan-result');
  const dateAt = (date,days) => {const d=new Date(date+'T12:00:00Z'); d.setUTCDate(d.getUTCDate()+days); return d.toLocaleDateString('en-AU',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});};
  const number = n => n.toLocaleString('en-AU',{maximumFractionDigits:1});
  function renderPlan(showValidation = false) {
    if (!form.checkValidity()) {
      if (showValidation) { tool.querySelector('.harvest-settings').open=true; form.reportValidity(); }
      result.innerHTML='<div class="harvest-empty"><span>🌱</span><h3>Let’s build your plan</h3><p>Add the yield per plant and harvest window in growing details to get started.</p></div>';
      return;
    }
    try {
      const v = Object.fromEntries(['grams','people','weeks','yieldGrams','windowWeeks','intervalDays'].map(k=>[k,Number(field(k).value)]));
      const p = calculatePlan(v);
      const start = field('start').value;
      const maturity = Number(field('maturityDays').value);
      const season = seasonalSchedule(v,p,start,months,maturity);
      const effectiveStart = season.rows[0].sow;
      const dates = season.rows.map((row,i)=> `<tr><td>${i+1}</td><td>${dateAt(row.sow,0)}</td><td>${row.plants}</td><td>${maturity>0?dateAt(row.sow,maturity):'Not recorded'}</td></tr>`).join('');
      result.innerHTML = `<span class="harvest-step">2 · Your planting plan</span><p class="harvest-target">${number(p.weeklyGrams)} g each week for ${v.people} ${v.people===1?'person':'people'}</p><div class="harvest-main-result"><strong>${p.firstBatch}</strong><div>plants to start<span>then ${p.plantsPerBatch} plants every ${v.intervalDays} days</span></div></div><div class="harvest-plan-strip"><span><b>${season.rows.length}</b> batches</span><span><b>${season.totalPlants}</b> plants total</span><span><b>${v.weeks}</b> weeks planned</span></div><p class="harvest-basis">Using the saved ${number(v.yieldGrams/1000)} kg yield per plant over ${v.windowWeeks} productive weeks.</p>${p.gapDays>0?`<p class="harvest-warning">There’s a ${number(p.gapDays)}-day gap between harvest windows. Reduce your sowing interval to ${number(v.windowWeeks*7)} days or less for steady supply.</p>`:''}${season.moved?`<p class="harvest-basis">First sowing moved to ${dateAt(effectiveStart,0)}, the next recorded planting season.</p>`:''}${season.skipped.length?`<p class="harvest-warning">${season.skipped.length} sowings fall outside this plant’s planting season and have been left out.${season.shortDays?` The target falls short on ${season.shortDays} days. Add another seasonal crop to cover the gap.`:''}</p>`:''}<p class="harvest-basis">${season.seasonRecorded?'Planting season: '+months.map(m=>m.slice(0,3)).join(', '):'No planting season is recorded.'}</p><p class="harvest-first-date">${maturity>0?'First harvest around '+dateAt(effectiveStart,maturity):'Days to first harvest are not recorded for this plant.'}</p><details class="harvest-dates"><summary>See your sowing schedule <span>↓</span></summary><table class="harvest-schedule"><thead><tr><th>Batch</th><th>Sow</th><th>Plants</th><th>First harvest</th></tr></thead><tbody>${dates}</tbody></table><p class="harvest-basis">Supply starts with your first harvest. Only sowings within the recorded planting months are included.</p></details>`;
    } catch(error) {result.textContent=error.message;}
  }
  form.addEventListener('submit', event => {event.preventDefault(); renderPlan(true);});
  form.addEventListener('input', () => renderPlan());
  renderPlan();
})();
