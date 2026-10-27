const {test}=require('node:test');
const assert=require('node:assert/strict');
const {calculatePlan}=require('../../static/harvest-calculator.js');
const base={grams:300,people:3,weeks:12,yieldGrams:500,windowWeeks:4,intervalDays:14};
test('household demand, startup and succession batches',()=>{
 const p=calculatePlan(base);
 assert.equal(p.weeklyGrams,900);assert.equal(p.firstBatch,8);assert.equal(p.plantsPerBatch,4);
 assert.equal(p.batchCount,6);assert.equal(p.totalPlants,28);assert.equal(p.totalTargetGrams,10800);
});
test('non-divisible harvest windows round conservatively',()=>{
 const p=calculatePlan({...base,windowWeeks:5});
 assert.equal(p.minimumOverlap,2);assert.equal(p.plantsPerBatch,5);
 assert.ok(p.minimumOverlap*p.plantsPerBatch*base.yieldGrams/5>=900);
});
test('reports a gap instead of promising continuous supply',()=>assert.equal(calculatePlan({...base,intervalDays:35}).gapDays,7));
test('rejects missing yield and fractional people',()=>{
 assert.throws(()=>calculatePlan({...base,yieldGrams:0}));assert.throws(()=>calculatePlan({...base,people:2.5}));
});
const {seasonalSchedule,recordedMaturity}=require('../../static/harvest-calculator.js');
test('uses the recorded first harvest timing without inventing a value',()=>{
 assert.equal(recordedMaturity('The supplier gives about 80 days to first harvest.'),80);
 assert.equal(recordedMaturity('Harvest for 8 weeks.'),null);
 assert.equal(recordedMaturity('70–90 days to first harvest'),90);
});
test('moves out-of-season sowing to the next recorded month',()=>{
 const v={...base,weeks:4};const p=calculatePlan(v);
 const season=seasonalSchedule(v,p,'2026-06-01',['September','October'],80);
 assert.equal(season.rows[0].sow,'2026-09-01');assert.equal(season.moved,92);
});
test('excludes out-of-season batches and reports supply shortfall',()=>{
 const p=calculatePlan(base);const season=seasonalSchedule(base,p,'2026-10-27',['October','November'],80);
 assert.ok(season.skipped.length>0);assert.ok(season.shortDays>0);
 assert.ok(season.rows.every(r=>[10,11].includes(Number(r.sow.slice(5,7)))));
 assert.equal(season.totalPlants,season.rows.reduce((n,r)=>n+r.plants,0));
});
