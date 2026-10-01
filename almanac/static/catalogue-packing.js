
/* Place each group in neighbouring grid cells, filling earlier empty spaces. */
window.packPlantGroups = function () {
  const grid = document.querySelector('.plant-groups');
  if (!grid) return;
  const columns = Math.max(1, Number(getComputedStyle(grid).getPropertyValue('--catalogue-columns')));
  const occupied = new Map();
  const groups = [...grid.querySelectorAll('.plant-group')];
  groups.forEach((group, groupIndex) => {
    const slots = [...group.querySelectorAll('.variety-slot')].filter(slot => getComputedStyle(slot).display !== 'none');
    const heading = group.querySelector('.plant-group-heading');
    const first = group.querySelector('[data-group-first]');
    if (heading.parentElement !== first) first.prepend(heading);
    let start = 0;
    while (occupied.has(start)) start++;
    const cells = [start];
    occupied.set(start, groupIndex);
    while (cells.length < slots.length) {
      const candidates = new Set();
      cells.forEach(cell => {
        const col = cell % columns;
        if (col > 0) candidates.add(cell - 1);
        if (col < columns - 1) candidates.add(cell + 1);
        candidates.add(cell + columns);
      });
      const next = [...candidates].filter(cell => !occupied.has(cell)).sort((a,b) => a-b)[0];
      cells.push(next);
      occupied.set(next, groupIndex);
    }
    cells.sort((a,b) => a-b);
    slots.forEach((slot, index) => {
      const cell = cells[index];
      slot.style.gridRow = Math.floor(cell / columns) + 1;
      slot.style.gridColumn = cell % columns + 1;
      slot.dataset.cell = cell;
      slot.dataset.group = groupIndex;
    });
  });
  grid.classList.add('is-packed');
  grid.querySelectorAll('.variety-slot').forEach(slot => {
    const cell = Number(slot.dataset.cell), group = Number(slot.dataset.group);
    const col = cell % columns;
    const joins = [
      occupied.get(cell-columns) === group,
      col < columns-1 && occupied.get(cell+1) === group,
      occupied.get(cell+columns) === group,
      col > 0 && occupied.get(cell-1) === group
    ];
    slot.style.borderWidth = joins.map(join => join ? '0px' : '6px').join(' ');
  });
};
window.packPlantGroups();
window.addEventListener('resize', window.packPlantGroups);
