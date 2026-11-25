const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('ui/quota_view.js','utf8');
const context=vm.createContext({Date,Map,Number,String,Object,Array,Math,console});vm.runInContext(source,context);
const state={account_observation:{usage:{observed_at:'2026-11-25T12:00:00Z',values:{limits:[{kind:'weekly_scoped',percent:90,is_active:true,scope:{model:{display_name:'Fable 5'}},resets_at:'2026-12-03T03:00:00Z'}]}}}};
let result=context.accountQuotaWindows(state);assert.equal(result.find(x=>x.label.includes('Fable')).percent,90);
state.account_observation.usage.values.limits[0].percent=5;
result=context.accountQuotaWindows(state);assert.equal(result.find(x=>x.label.includes('Fable')).percent,5);
state.quota_observation={observed_at:'2026-11-25T13:00:00Z',signals:{'Anthropic-Ratelimit-Unified-7d_oi-Utilization':'.09'}};
assert.equal(context.accountQuotaWindows(state).find(x=>x.label.includes('Fable')).percent,9);
assert.equal(context.accountQuotaWindows({})[0].percent,undefined);
console.log('quota windows: updated Fable values, newer passive observation and missing values passed');

const grantState={account_observation:{usage:{values:{cedar_ember:{eligible:true,at_limit:false,grants:[{id:'a',resets_left:2,usable_now:true,paused:false,use_requires_limit:false,ends_at:'2026-12-01T00:00:00Z'}]}}}}};
assert.equal(context.resetGrantSummary(grantState,Date.parse('2026-11-25')).left,2);
assert.equal(context.resetGrantSummary(grantState,Date.parse('2026-12-02')).left,0);
assert.equal(context.resetGrantSummary({}).reported,false);
grantState.account_observation.usage.values.cedar_ember.grants[0].resets_left=undefined;
assert.equal(context.resetGrantSummary(grantState,Date.parse('2026-11-25')).left,undefined);
console.log('reset grant count, expiry and unknown data passed');
